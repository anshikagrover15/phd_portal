document.addEventListener('DOMContentLoaded', () => {
  console.log('Live Sheet app initialized.');

  const list = document.getElementById('offer-list');
  if (!list) return;  // not on the dashboard

  const csrfInput = list.querySelector('input[name="csrfmiddlewaretoken"]')
    || document.querySelector('input[name="csrfmiddlewaretoken"]');
  const alertBox = document.getElementById('offer-alert');
  if (!csrfInput || !alertBox) {
    console.error('Offer list: missing CSRF token input or the #offer-alert element in dashboard.html');
    return;
  }
  const csrfToken = csrfInput.value;
  function showAlert(message, ok) {
    alertBox.textContent = message;
    alertBox.className = 'alert ' + (ok ? 'alert--success' : 'alert--error');
    alertBox.hidden = false;
  }

  function setStatus(el, message, ok) {
    el.textContent = message;
    el.className = 'inline-status ' + (ok ? 'inline-status--success' : 'inline-status--error');
  }

  async function postOffer(url, fields) {
    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest' },
        body: new URLSearchParams(fields),
      });
    } catch (err) {
      return { ok: false, error: 'Network error. Please try again.' };
    }
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      if (response.redirected) return { ok: false, error: 'Your session has expired. Please log in again.' };
      if (response.status === 403) return { ok: false, error: 'You do not have permission to do this.' };
      return { ok: false, error: `Save failed (HTTP ${response.status}).` };
    }
    return response.json();
  }

  async function saveText(cell) {
    const control = cell.querySelector('.inline-input');
    const button = cell.querySelector('.inline-save');
    const status = cell.querySelector('.inline-status');
    const field = control.dataset.field;

    button.disabled = true;
    setStatus(status, 'Saving…', true);
    const result = await postOffer(control.dataset.url, { [field]: control.value });
    button.disabled = false;

    if (result.ok) {
      control.value = result[field];
      control.dataset.original = result[field];
      control.classList.remove('is-dirty');
      setStatus(status, 'Saved', true);
      showAlert(result.message, true);
    } else {
      setStatus(status, 'Not saved', false);
      showAlert(result.error, false);
    }
  }

  list.addEventListener('click', (event) => {
    const button = event.target.closest('.inline-save');
    if (button) saveText(button.closest('.offer-edit-cell'));
  });

  list.addEventListener('input', (event) => {
    const control = event.target.closest('.inline-input');
    if (control) control.classList.toggle('is-dirty', control.value !== control.dataset.original);
  });

  // Enter saves a single-line input; a textarea keeps Enter for new lines.
  list.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && event.target.matches('input.inline-input')) {
      event.preventDefault();
      saveText(event.target.closest('.offer-edit-cell'));
    }
  });

  list.addEventListener('change', async (event) => {
    const toggle = event.target.closest('.withdraw-toggle');
    if (!toggle) return;
    const cell = toggle.closest('.offer-edit-cell');
    const status = cell.querySelector('.inline-status');
    const wanted = toggle.checked;

    toggle.disabled = true;
    setStatus(status, 'Saving…', true);
    const result = await postOffer(toggle.dataset.url, { withdrawn: wanted ? 'true' : 'false' });
    toggle.disabled = false;

    if (result.ok) {
      toggle.checked = result.withdrawn;
      toggle.closest('tr').classList.toggle('is-withdrawn', result.withdrawn);
      setStatus(status, 'Saved', true);
      showAlert(result.message, true);
    } else {
      toggle.checked = !wanted;  // put the checkbox back to what the database holds
      setStatus(status, 'Not saved', false);
      showAlert(result.error, false);
    }
  });
});
