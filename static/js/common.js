(function(){
  'use strict';
  const HydroUI={
    isDark(){return document.documentElement.getAttribute('data-theme')==='dark';},
    refreshIcons(){if(window.lucide)window.lucide.createIcons({attrs:{'stroke-width':2}});},
    applyTheme(theme){
      const dark=theme==='dark';
      if(dark)document.documentElement.setAttribute('data-theme','dark'); else document.documentElement.removeAttribute('data-theme');
      try{localStorage.setItem('theme',dark?'dark':'light')}catch(_){}
      const icon=document.getElementById('themeIcon');if(icon)icon.setAttribute('data-lucide',dark?'sun':'moon');
      this.refreshIcons();
      document.dispatchEvent(new CustomEvent('hydro:themechange',{detail:{theme:dark?'dark':'light'}}));
    },
    toggleTheme(){this.applyTheme(this.isDark()?'light':'dark');},
    enhanceFieldHelp(root=document){
      // Custom hover-tip UI intentionally disabled.
      document.getElementById('fieldHelpTooltip')?.remove();
      root.querySelectorAll('.field-help').forEach(el=>el.remove());
    }
  };
  window.HydroUI=HydroUI;
  document.addEventListener('DOMContentLoaded',()=>{
    const icon=document.getElementById('themeIcon');if(icon)icon.setAttribute('data-lucide',HydroUI.isDark()?'sun':'moon');
    document.getElementById('themeToggleBtn')?.addEventListener('click',()=>HydroUI.toggleTheme());
    HydroUI.enhanceFieldHelp();HydroUI.refreshIcons();
  });
})();
