// Theme toggle for the slop-check site. The inline script in the page head sets
// data-theme from a stored choice or from prefers-color-scheme before first paint.
// This file wires the toggle button and follows OS changes while no choice is stored.
(function () {
  var root = document.documentElement;
  var key = 'slopcheck-theme';
  var button = document.querySelector('[data-theme-toggle]');

  function storedTheme() {
    try {
      var value = window.localStorage.getItem(key);
      return value === 'light' || value === 'dark' ? value : null;
    } catch (e) {
      return null;
    }
  }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    if (button) {
      button.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
    }
  }

  apply(root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');

  if (button) {
    button.hidden = false;
    button.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      apply(next);
      try {
        window.localStorage.setItem(key, next);
      } catch (e) {
        // Storage can be unavailable (private mode, blocked site data). The choice then lasts for this page only.
      }
    });
  }

  if (window.matchMedia) {
    var query = window.matchMedia('(prefers-color-scheme: dark)');
    var onChange = function (event) {
      if (!storedTheme()) {
        apply(event.matches ? 'dark' : 'light');
      }
    };
    if (query.addEventListener) {
      query.addEventListener('change', onChange);
    } else if (query.addListener) {
      query.addListener(onChange);
    }
  }
})();
