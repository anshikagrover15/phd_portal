// Checkbox dropdown filters (<details class="multi-select" data-simple>): nothing ticked means "all".
(function () {
  function label(menu) {
    var boxes = menu.querySelectorAll('input[type=checkbox]');
    var ticked = Array.prototype.filter.call(boxes, function (b) { return b.checked; });
    var text = menu.querySelector('.multi-select-summary');
    var all = menu.getAttribute('data-all-label') || 'All';
    if (ticked.length === 0) text.textContent = all;
    else if (ticked.length === 1) text.textContent = ticked[0].nextElementSibling.textContent.trim();
    else text.textContent = ticked.length + ' selected';
  }
  document.addEventListener('DOMContentLoaded', function () {
    var menus = document.querySelectorAll('.multi-select[data-simple]');
    menus.forEach(function (menu) {
      label(menu);
      menu.addEventListener('change', function () { label(menu); });
      menu.querySelectorAll('[data-action="none"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          menu.querySelectorAll('input[type=checkbox]').forEach(function (b) { b.checked = false; });
          label(menu);
        });
      });
      menu.addEventListener('toggle', function () {
        if (menu.open) menus.forEach(function (o) { if (o !== menu) o.open = false; });
      });
    });
    document.addEventListener('click', function (e) {
      menus.forEach(function (m) { if (!m.contains(e.target)) m.open = false; });
    });
  });
})();
