// Non-blocking hint shown when a personal-profile form looks like it's being
// used to set up a robotics *team* instead of an individual. It never blocks
// submission — it just offers a shortcut to the separate team-creation flow.
//
// Signals (see the scoring below), kept conservative to avoid false positives on
// real people's names:
//   - display name contains the word "team"          (strong, triggers alone)
//   - display name contains "robotics"               (weak)
//   - display name contains a 3-5 digit number       (moderate — FTC-style number)
//   - username is a bare 3-5 digit number            (strong, triggers alone)
// Image/logo detection is intentionally omitted: it can't be done reliably or
// privacy-appropriately on the client, and the spec only asks for it when it can.
(function () {
  'use strict';

  var TRIGGER_SCORE = 3;
  var TEAMS_URL = '/teams';

  function score(name, username) {
    var s = 0;
    var text = (name || '').trim();
    if (/\bteam\b/i.test(text)) s += 3;
    if (/robotics/i.test(text)) s += 1;
    if (/\b\d{3,5}\b/.test(text)) s += 2;
    if (/^\d{3,5}$/.test((username || '').trim())) s += 3;
    return s;
  }

  function buildWarning() {
    var box = document.createElement('div');
    box.className = 'team-detect-warning';
    box.setAttribute('role', 'status');
    box.hidden = true;

    var msg = document.createElement('p');
    msg.textContent = 'Are you setting up a robotics team? Team pages should be created separately.';
    box.appendChild(msg);

    var actions = document.createElement('div');
    actions.className = 'team-detect-warning__actions';

    var create = document.createElement('a');
    create.className = 'btn btn--quiet btn--sm';
    create.href = TEAMS_URL;
    create.textContent = 'Create Team Page';
    actions.appendChild(create);

    var keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'text-button';
    keep.textContent = 'Continue with Personal Profile';
    actions.appendChild(keep);

    box.appendChild(actions);
    return { box: box, dismiss: keep };
  }

  function wire(form) {
    var nameInput = form.querySelector('[data-team-detect-name]');
    if (!nameInput) return;
    var username = form.getAttribute('data-team-detect-username') || '';

    var built = buildWarning();
    // Place the hint right after the name field so it reads in context.
    var anchor = nameInput.closest('label') || nameInput;
    anchor.parentNode.insertBefore(built.box, anchor.nextSibling);

    var dismissed = false;
    built.dismiss.addEventListener('click', function () {
      dismissed = true;
      built.box.hidden = true;
    });

    function evaluate() {
      if (dismissed) return;
      built.box.hidden = score(nameInput.value, username) < TRIGGER_SCORE;
    }

    nameInput.addEventListener('input', evaluate);
    nameInput.addEventListener('blur', evaluate);
    evaluate();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var forms = document.querySelectorAll('form[data-team-detect]');
    for (var i = 0; i < forms.length; i++) wire(forms[i]);
  });
})();
