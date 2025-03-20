// 导航栏滚动隐藏和显示
let lastScrollTop = 0;
const nav = document.querySelector('nav');

window.addEventListener('scroll', () => {
    let currentScrollTop = window.pageYOffset || document.documentElement.scrollTop;

    if (currentScrollTop > lastScrollTop) {
        // 向下滚动，隐藏导航栏
        nav.style.transform = 'translateY(-100%)';
    } else {
        // 向上滚动，显示导航栏
        nav.style.transform = 'translateY(0)';
    }
    lastScrollTop = currentScrollTop <= 0 ? 0 : currentScrollTop; // 防止负值
});