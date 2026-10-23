
const defaults = { theme: 'dark', navigation: true, left: true, right: false, bottom: false, leftWidth: 220, rightWidth: 300 };
export function readPreferences(storage = localStorage) {
  try {
    const value = JSON.parse(storage.getItem('novel-ui') || '{}');
    return {
      theme: value.theme === 'light' ? 'light' : 'dark',
      navigation: typeof value.navigation === 'boolean' ? value.navigation : true,
      left: typeof value.left === 'boolean' ? value.left : true,
      right: typeof value.right === 'boolean' ? value.right : false,
      bottom: typeof value.bottom === 'boolean' ? value.bottom : false,
      leftWidth: Math.max(180, Math.min(340, Number(value.leftWidth) || defaults.leftWidth)),
      rightWidth: Math.max(220, Math.min(380, Number(value.rightWidth) || defaults.rightWidth)),
    };
  } catch { return { ...defaults }; }
}
export function writePreferences(preferences, storage = localStorage) {
  try { storage.setItem('novel-ui', JSON.stringify(readPreferences({ getItem: () => JSON.stringify(preferences) }))); } catch { /* 存储不可用时本窗口继续可用。 */ }
}

export function createLayout() {
  const preferences = readPreferences();
  const bench = document.querySelector('#workbench');
  let focused = false, drawer = '', returnFocus = null;
  let autoLeft = false, autoRight = false;
  let view='chat';
  let homeBottom=false;
  function apply() {
    document.documentElement.dataset.theme = preferences.theme;
    bench.style.setProperty('--left-width', preferences.leftWidth + 'px');
    bench.style.setProperty('--right-width', preferences.rightWidth + 'px');
    const home=view==='chat';
    bench.classList.toggle('chat-mode', home);
    document.body.classList.toggle('chat-active',home);
    bench.classList.toggle('left-hidden', focused || home || !preferences.left);
    bench.classList.toggle('right-hidden', focused || home || !preferences.right);
    bench.classList.toggle('modules-collapsed', !home&&!preferences.navigation);
    bench.classList.toggle('modules-open',home&&drawer==='modules');
    const navWidth=home?0:innerWidth<=760?48:preferences.navigation?204:56;
    bench.style.setProperty('--nav-width',navWidth+'px');
    // 给正文保留至少 560px 可用宽度（含表单/滚动槽预留约 100px）。
    const leftSpace=!focused&&!home&&preferences.left?preferences.leftWidth+5:0;
    const rightSpace=!focused&&!home&&preferences.right?preferences.rightWidth+5:0;
    autoRight=innerWidth<1200 || innerWidth-navWidth-leftSpace-rightSpace<660;
    autoLeft=innerWidth<=760 || innerWidth-navWidth-leftSpace-(autoRight?0:rightSpace)<660;
    bench.classList.toggle('auto-right',autoRight);
    bench.classList.toggle('auto-left',autoLeft);
    bench.classList.toggle('left-drawer', drawer === 'left');
    bench.classList.toggle('right-drawer', drawer === 'right');
    bench.style.setProperty('--dock-left', !focused&&!home&&preferences.left&&!autoLeft?preferences.leftWidth+'px':'0px');
    bench.style.setProperty('--dock-right', !focused&&!home&&preferences.right&&!autoRight?preferences.rightWidth+'px':'0px');
    bench.style.setProperty('--divider-left', !focused&&!home&&preferences.left&&!autoLeft?'5px':'0px');
    bench.style.setProperty('--divider-right', !focused&&!home&&preferences.right&&!autoRight?'5px':'0px');
    document.querySelector('#bottom-panel').hidden = focused || (home ? !homeBottom : !preferences.bottom);
    document.querySelector('#drawer-backdrop').hidden = !drawer;
    document.querySelector('#focus-mode').textContent = focused ? '退出专注' : '专注';
    const moduleToggle=document.querySelector('#toggle-modules');
    const expanded=home?drawer==='modules':preferences.navigation&&innerWidth>760;
    moduleToggle.setAttribute('aria-label',expanded?'折叠模块导航':'展开模块导航');
    moduleToggle.title=expanded?'收起创作模块':'打开创作模块';
    moduleToggle.setAttribute('aria-expanded',String(expanded));
    for (const side of ['left', 'right']) {
      const visible = document.querySelector(`#${side}-panel`).getBoundingClientRect().width > 0;
      document.querySelector(`#toggle-${side}`).setAttribute('aria-expanded', String(visible));
      document.querySelector(`#${side}-resize`).setAttribute('aria-valuenow', preferences[side + 'Width']);
    }
    document.querySelector('#toggle-bottom').setAttribute('aria-expanded', String(!document.querySelector('#bottom-panel').hidden));
    document.querySelector('#quick-activity').setAttribute('aria-expanded', String(!document.querySelector('#bottom-panel').hidden));
    document.dispatchEvent(new Event('novel-layout-change'));
  }
  function closeDrawer(restore = true) {
    drawer = ''; apply();
    if (restore && returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  }
  function toggle(side) {
    focused = false;
    if (view==='chat' || (side === 'left' && autoLeft) || (side === 'right' && autoRight)) {
      if (drawer === side) { closeDrawer(); return; }
      drawer = side; returnFocus = document.querySelector(`#toggle-${side}`);
      apply(); document.querySelector(`#${side}-panel button`).focus();
    } else { closeDrawer(false); preferences[side] = !preferences[side]; apply(); writePreferences(preferences); }
  }
  function focus() { closeDrawer(false); focused = !focused; apply(); }
  function theme() { preferences.theme = preferences.theme === 'light' ? 'dark' : 'light'; apply(); writePreferences(preferences); }
  function bottom(value) {
    if(value===undefined)value=view==='chat'?!homeBottom:!preferences.bottom;
    focused=false;
    if(view==='chat')homeBottom=value;else preferences.bottom=value;
    apply();writePreferences(preferences);
  }
  for (const side of ['left', 'right']) {
    const divider = document.querySelector(`#${side}-resize`);
    const minimum = Number(divider.getAttribute('aria-valuemin')), maximum = Number(divider.getAttribute('aria-valuemax'));
    function resize(value) { preferences[side + 'Width'] = Math.max(minimum, Math.min(maximum, value)); apply(); }
    divider.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const direction = side === 'left' ? 1 : -1;
      resize(event.key === 'Home' ? minimum : event.key === 'End' ? maximum : preferences[side + 'Width'] + (event.key === 'ArrowRight' ? 20 : -20) * direction);
      writePreferences(preferences);
    });
    divider.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault(); divider.setPointerCapture(event.pointerId);
      const initial = preferences[side + 'Width'], start = event.clientX;
      const move = next => resize(initial + (next.clientX - start) * (side === 'left' ? 1 : -1));
      const end = () => { divider.removeEventListener('pointermove', move); divider.removeEventListener('pointerup', end); divider.removeEventListener('pointercancel', end); writePreferences(preferences); };
      divider.addEventListener('pointermove', move); divider.addEventListener('pointerup', end); divider.addEventListener('pointercancel', end);
    });
  }
  document.addEventListener('keydown', event => {
    if (!drawer || document.querySelector('dialog[open], :popover-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); }
    if (event.key === 'Tab') {
      const panel = document.querySelector(drawer==='modules'?'#tabs':`#${drawer}-panel`);
      const list = [...panel.querySelectorAll('button:not(:disabled),input,select,a[href],[tabindex="0"]')].filter(el => el.getClientRects().length);
      const index = list.indexOf(document.activeElement);
      if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === list.length - 1) || index < 0) { event.preventDefault(); list[event.shiftKey ? list.length - 1 : 0]?.focus(); }
    }
  });
  window.addEventListener('resize', () => closeDrawer(false));
  apply();
  return { toggle, closeDrawer, focus, theme, bottom,
    setView(value) { if(view!==value){homeBottom=false;drawer='';returnFocus=null;}view=value;apply(); },
    isDrawer() { return Boolean(drawer); },
    modules() {
      if(view==='chat') {
        if(drawer==='modules'){closeDrawer();return;}
        drawer='modules';returnFocus=document.querySelector('#toggle-modules');
        apply();document.querySelector('#tabs button:not(:disabled)')?.focus();return;
      }
      preferences.navigation=!preferences.navigation;apply();writePreferences(preferences);
    },
    show(side) {
      if(drawer===side)return;
      if(view==='chat'||side==='left'&&autoLeft||side==='right'&&autoRight) { toggle(side);return; }
      focused=false;preferences[side]=true;apply();writePreferences(preferences);
    },
    close(side) { if (drawer) closeDrawer(); else { preferences[side] = false; apply(); writePreferences(preferences); document.querySelector(`#toggle-${side}`).focus(); } }
  };
}
