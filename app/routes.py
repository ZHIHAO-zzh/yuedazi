from flask import render_template, redirect, url_for, flash, request
from app.models import User, Activity, Participation, Message
from app.forms import LoginForm, RegistrationForm, ActivityForm, ProfileForm
from flask_login import current_user, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import emit
from flask_socketio import join_room
from sqlalchemy.exc import IntegrityError
import sqlalchemy as sa
import pytz
from datetime import datetime

def to_local_time(utc_time, timezone='Asia/Shanghai'):
    local_tz = pytz.timezone(timezone)
    if utc_time.tzinfo is None:
        utc_time = pytz.UTC.localize(utc_time)
    local_time = utc_time.astimezone(local_tz)
    return local_time

def init_routes(app, db, socketio):
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and check_password_hash(user.password_hash, form.password.data):
                login_user(user, remember=form.remember_me.data)
                return redirect(url_for('index'))
            flash('Invalid username or password')
        return render_template('login.html', title='Sign In', form=form)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = RegistrationForm()
        if form.validate_on_submit():
            existing_user = User.query.filter_by(email=form.email.data).first()
            if existing_user:
                flash('该邮箱已被注册，请使用其他邮箱。', 'error')
            else:
                existing_user = User.query.filter_by(username=form.username.data).first()
                if existing_user:
                    flash('该用户名已被使用，请选择其他用户名。', 'error')
                else:
                    user = User(
                        username=form.username.data,
                        email=form.email.data,
                        password_hash=generate_password_hash(form.password.data)
                    )
                    db.session.add(user)
                    db.session.commit()
                    flash('注册成功！', 'success')
                    return redirect(url_for('login'))
        return render_template('register.html', title='Register', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    @app.route('/')
    @app.route('/index', methods=['GET', 'POST'])
    def index():
        sort = request.args.get('sort', 'created_at')
        search = request.args.get('search', '')
        query = Activity.query
        if search:
            query = query.filter(Activity.title.contains(search) | Activity.description.contains(search))
        if sort == 'event_time':
            activities = query.order_by(Activity.event_time.asc()).all()
        else:
            activities = query.order_by(Activity.created_at.desc()).all()
        
        recent_chats = []
        if current_user.is_authenticated:
            subquery = db.session.query(
                Message.conversation_id,
                sa.func.max(Message.timestamp).label('max_timestamp')
            ).filter(
                Message.id.isnot(None) &
                ((Message.sender_id == current_user.id) | (Message.receiver_id == current_user.id))
            ).group_by(Message.conversation_id).subquery()

            recent_chats_query = db.session.query(Message, Activity).join(
                subquery,
                (Message.conversation_id == subquery.c.conversation_id) &
                (Message.timestamp == subquery.c.max_timestamp)
            ).join(Activity, Message.activity_id == Activity.id).order_by(
                subquery.c.max_timestamp.desc()
            ).limit(5)

            recent_chats = []
            for message, activity in recent_chats_query.all():
                other_user_id = message.receiver_id if message.sender_id == current_user.id else message.sender_id
                other_user = User.query.get(other_user_id)
                local_timestamp = to_local_time(message.timestamp)
                recent_chats.append({
                    'conversation_id': message.conversation_id,
                    'activity': activity,
                    'other_user': other_user,
                    'last_message': message,
                    'local_timestamp': local_timestamp
                })
            print("Recent chats:", [(chat['activity'].title, chat['other_user'].username, chat['local_timestamp'].strftime('%Y-%m-%d %H:%M')) for chat in recent_chats])

        return render_template('index.html', title='Activity Square', activities=activities,
                            search=search, sort=sort, recent_chats=recent_chats)

    @app.route('/activity/create', methods=['GET', 'POST'])
    @login_required
    def activity_create():
        form = ActivityForm()
        if form.validate_on_submit():
            if form.end_time.data <= form.event_time.data:
                flash('结束时间必须晚于开始时间。', 'error')
                return render_template('activity_create.html', title='Create Activity', form=form)
            activity = Activity(
                title=form.title.data,
                description=form.description.data,
                creator_id=current_user.id,
                event_time=form.event_time.data,
                end_time=form.end_time.data,
                location=form.location.data,
                max_participants=form.max_participants.data
            )
            db.session.add(activity)
            db.session.commit()
            socketio.emit('new_activity', {
                'id': activity.id,
                'title': activity.title,
                'creator': activity.creator.username,
                'event_time': to_local_time(activity.event_time).strftime('%Y-%m-%d %H:%M'),
                'end_time': to_local_time(activity.end_time).strftime('%Y-%m-%d %H:%M') if activity.end_time else None
            })
            flash('活动创建成功！', 'success')
            return redirect(url_for('index'))
        return render_template('activity_create.html', title='Create Activity', form=form)

    @app.route('/activity/<int:activity_id>')
    def activity_detail(activity_id):
        activity = Activity.query.get_or_404(activity_id)
        participations = Participation.query.filter_by(activity_id=activity_id).all()
        return render_template('activity_detail.html', title=activity.title, activity=activity, participations=participations)

    @app.route('/activity/<int:activity_id>/join')
    @login_required
    def activity_join(activity_id):
        activity = Activity.query.get_or_404(activity_id)
        if Participation.query.filter_by(user_id=current_user.id, activity_id=activity_id).first():
            flash('You have already joined this activity.')
        elif activity.participants.count() >= activity.max_participants:
            flash('This activity is full.')
        else:
            participation = Participation(user_id=current_user.id, activity_id=activity_id)
            db.session.add(participation)
            db.session.commit()
            flash('You have joined the activity!')
        return redirect(url_for('activity_detail', activity_id=activity_id))

    @app.route('/activity/manage')
    @login_required
    def activity_manage():
        created_activities = Activity.query.filter_by(creator_id=current_user.id).all()
        joined_activities = [p.activity for p in Participation.query.filter_by(user_id=current_user.id).all()]
        return render_template('activity_manage.html', title='Manage Activities',
                              created_activities=created_activities, joined_activities=joined_activities)

    @app.route('/activity/edit/<int:activity_id>', methods=['GET', 'POST'])
    @login_required
    def activity_edit(activity_id):
        activity = Activity.query.get_or_404(activity_id)
        if activity.creator_id != current_user.id:
            flash('您无权编辑此活动。', 'error')
            return redirect(url_for('activity_manage'))
        form = ActivityForm()
        if form.validate_on_submit():
            activity.title = form.title.data
            activity.description = form.description.data
            activity.event_time = form.event_time.data
            activity.end_time = form.end_time.data
            activity.location = form.location.data
            activity.max_participants = form.max_participants.data
            db.session.commit()
            flash('活动已更新！', 'success')
            return redirect(url_for('activity_manage'))
        elif request.method == 'GET':
            form.title.data = activity.title
            form.description.data = activity.description
            form.event_time.data = activity.event_time
            form.end_time.data = activity.end_time
            form.location.data = activity.location
            form.max_participants.data = activity.max_participants
        return render_template('activity_edit.html', form=form, activity=activity)

    @app.route('/activity/delete/<int:activity_id>', methods=['POST'])
    @login_required
    def activity_delete(activity_id):
        activity = Activity.query.get_or_404(activity_id)
        if activity.creator_id != current_user.id:
            flash('您无权删除此活动。', 'error')
            return redirect(url_for('activity_manage'))
        db.session.delete(activity)
        db.session.commit()
        socketio.emit('delete_activity', {'id': activity_id})
        flash('活动已删除！', 'success')
        return redirect(url_for('activity_manage'))

    @app.route('/activity/leave/<int:activity_id>', methods=['POST'])
    @login_required
    def activity_leave(activity_id):
        activity = Activity.query.get_or_404(activity_id)
        participation = Participation.query.filter_by(user_id=current_user.id, activity_id=activity_id).first()
        if not participation:
            flash('您未参与此活动。', 'error')
            return redirect(url_for('activity_manage'))
        db.session.delete(participation)
        db.session.commit()
        flash('您已退出该活动。', 'success')
        return redirect(url_for('activity_manage'))

    @app.route('/chat/<conversation_id>')
    @login_required
    def chat(conversation_id):
        # 查询消息记录
        messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.timestamp.asc()).all()
        
        # 从 conversation_id 解析 activity_id 和 user_ids
        try:
            activity_id, user1_id, user2_id = map(int, conversation_id.split('-'))
        except ValueError:
            flash('无效的会话 ID。', 'error')
            return redirect(url_for('index'))

        # 验证当前用户是否是会话的参与者
        if current_user.id not in (user1_id, user2_id):
            flash('您无权访问此会话。', 'error')
            return redirect(url_for('index'))

        # 获取活动信息
        activity = Activity.query.get(activity_id)
        if not activity:
            flash('活动不存在。', 'error')
            return redirect(url_for('index'))

        # 获取对方用户信息
        other_user_id = user1_id if current_user.id == user2_id else user2_id
        other_user = User.query.get(other_user_id)
        if not other_user:
            flash('用户不存在。', 'error')
            return redirect(url_for('index'))

        # 为消息添加本地时间（如果有消息）
        for message in messages:
            message.local_timestamp = to_local_time(message.timestamp)

        # 即使 messages 为空，也允许进入聊天页面
        return render_template('chat.html', title=f'Chat - {activity.title} - {other_user.username}', 
                             activity=activity, messages=messages, conversation_id=conversation_id, other_user=other_user)

    @socketio.on('send_message')
    def handle_send_message(data):
        activity_id = data['activity_id']
        content = data['content']
        receiver_id = data['receiver_id']
        activity = Activity.query.get(activity_id)
        if activity:
            user_ids = sorted([current_user.id, int(receiver_id)])
            conversation_id = f"{activity_id}-{user_ids[0]}-{user_ids[1]}"
            message = Message(
                sender_id=current_user.id,
                receiver_id=receiver_id,
                activity_id=activity_id,
                conversation_id=conversation_id,
                content=content
            )
            db.session.add(message)
            db.session.commit()
            print(f"Message saved and broadcasting to room {conversation_id}: {content}")
            emit('new_message', {'sender': current_user.username, 'content': content}, room=conversation_id)
            receiver = User.query.get(receiver_id)
            local_timestamp = to_local_time(message.timestamp)
            socketio.emit('new_chat_message', {
                'conversation_id': conversation_id,
                'activity_id': activity_id,
                'activity_title': activity.title,
                'other_user': receiver.username,
                'timestamp': local_timestamp.strftime('%Y-%m-%d %H:%M')
            })
        else:
            print(f"Activity {activity_id} not found")

    @socketio.on('join')
    def handle_join(data):
        room = str(data['room'])
        join_room(room)
        print(f"User joined room {room}")

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        form = ProfileForm(obj=current_user)
        if form.validate_on_submit():
            current_user.username = form.username.data
            current_user.email = form.email.data
            db.session.commit()
            flash('Profile updated!')
            return redirect(url_for('profile'))
        return render_template('profile.html', title='Profile', form=form)
    
    @app.route('/delete_account', methods=['POST'])
    @login_required
    def delete_account():
        user = current_user._get_current_object()
        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('您的账号已成功注销。', 'success')
        return redirect(url_for('index'))