(function () {
  function snapshot(select) {
    return Array.from(select.options).map(function (option) {
      return {
        value: option.value,
        text: option.text,
        disabled: option.disabled,
        selected: option.selected,
        group: option.parentElement && option.parentElement.tagName === 'OPTGROUP' ? option.parentElement.label : ''
      };
    });
  }

  function rebuild(select, options, query) {
    var selectedValue = select.value;
    var needle = (query || '').trim().toLocaleLowerCase();
    var filtered = options.filter(function (option) {
      return !needle || option.text.toLocaleLowerCase().includes(needle) || String(option.value).toLocaleLowerCase().includes(needle) || option.value === selectedValue;
    });
    select.innerHTML = '';
    var groups = {};
    filtered.forEach(function (item) {
      var parent = select;
      if (item.group) {
        if (!groups[item.group]) {
          groups[item.group] = document.createElement('optgroup');
          groups[item.group].label = item.group;
          select.appendChild(groups[item.group]);
        }
        parent = groups[item.group];
      }
      var option = document.createElement('option');
      option.value = item.value;
      option.textContent = item.text;
      option.disabled = item.disabled;
      option.selected = item.value === selectedValue || (!selectedValue && item.selected);
      parent.appendChild(option);
    });
  }

  function enhance(select) {
    if (!select || select.dataset.searchableReady === '1' || select.dataset.noSearch === 'true' || select.multiple) return;
    select.dataset.searchableReady = '1';
    var options = snapshot(select);
    var wrapper = document.createElement('div');
    wrapper.className = 'space-y-1';
    var search = document.createElement('input');
    search.type = 'search';
    search.autocomplete = 'off';
    search.placeholder = select.dataset.searchPlaceholder || 'Search options…';
    search.setAttribute('aria-label', 'Search ' + (select.getAttribute('aria-label') || select.name || 'options'));
    search.className = select.className || 'w-full rounded-md border border-input bg-background px-3 py-2 text-sm';
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(search);
    wrapper.appendChild(select);
    search.addEventListener('input', function () { rebuild(select, options, search.value); });
    search.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        select.focus();
      }
    });
    select.addEventListener('change', function () {
      if (search.value) {
        search.value = '';
        rebuild(select, options, '');
      }
    });
  }

  function init(root) {
    (root || document).querySelectorAll('select').forEach(enhance);
  }

  document.addEventListener('DOMContentLoaded', function () { init(document); });
  document.body && document.body.addEventListener('htmx:afterSwap', function (event) { init(event.detail.target || document); });
  window.ChakkiSearchableSelects = { init: init };
})();
