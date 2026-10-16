// The admin "upload for a team" picker (templates/_team_credit.html).
//
// An admin credits a design to any FTC or FRC team, most of which have no Botfolio
// account, so there is nothing to pick from a list. They type the number and the
// name is resolved for them; if they only know the name, the button swaps the
// number box for a search box and the matching teams become clickable.
//
// The posted form carries the number and - only when it has been confirmed for
// that exact number - the name. Every edit to the number clears the confirmed
// name again, so a stale label can never ride along with a different team. The
// server resolves the name a second time regardless (app.credit_team_name),
// which is what makes this whole control optional rather than load-bearing.
(function () {
  'use strict';

  var ENDPOINT = '/api/admin/team-credit';
  var DEBOUNCE_MS = 260;
  var MIN_QUERY = 2;

  function setup(fieldset) {
    var attribution = fieldset.querySelector('select[name="admin_attribution"]');
    var fields = fieldset.querySelector('.team-credit');
    var numberInput = fieldset.querySelector('[data-credit-number]');
    var searchInput = fieldset.querySelector('[data-credit-search]');
    var nameInput = fieldset.querySelector('[data-credit-name]');
    var toggle = fieldset.querySelector('[data-credit-toggle]');
    var status = fieldset.querySelector('[data-credit-status]');
    var results = fieldset.querySelector('[data-credit-results]');
    var programInput = document.getElementById('program-select');
    var numberField = fieldset.querySelector('[data-credit-field="number"]');
    var nameField = fieldset.querySelector('[data-credit-field="name"]');
    if (!attribution || !fields || !numberInput || !searchInput || !nameInput) return;

    var timer = null;
    var request = 0;

    function program() {
      return programInput && programInput.value === 'frc' ? 'frc' : 'ftc';
    }

    function programLabel() { return program().toUpperCase(); }

    function say(text, tone) {
      status.textContent = text || '';
      status.className = 'team-credit__status' + (tone ? ' is-' + tone : '');
    }

    function showResults(items) {
      results.innerHTML = '';
      if (!items || !items.length) {
        results.hidden = true;
        return;
      }
      items.forEach(function (team) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'team-credit__result';
        var line = document.createElement('span');
        line.className = 'team-credit__result-name';
        line.textContent = team.number + ' — ' + team.name;
        button.appendChild(line);
        var meta = [];
        if (team.location) meta.push(team.location);
        if (team.on_botfolio) meta.push('On Botfolio');
        if (meta.length) {
          var sub = document.createElement('span');
          sub.className = 'team-credit__result-meta';
          sub.textContent = meta.join(' · ');
          button.appendChild(sub);
        }
        button.addEventListener('click', function () { choose(team); });
        var item = document.createElement('li');
        item.appendChild(button);
        results.appendChild(item);
      });
      results.hidden = false;
    }

    function choose(team) {
      numberInput.value = team.number;
      nameInput.value = team.name;
      showResults(null);
      searchInput.value = '';
      setMode('number');
      say(team.number + ' — ' + team.name + (team.on_botfolio ? ' · on Botfolio' : ''), 'good');
    }

    // Neither half of this control blocks the upload: if the registry is down or
    // the number is unlisted, the credit still goes through under whatever the
    // server can resolve. So an unrecognised number is a note, not an error.
    function describe(state, team) {
      if (state === 'found' && team) {
        return [team.number + ' — ' + team.name +
                (team.location ? ' · ' + team.location : '') +
                (team.on_botfolio ? ' · on Botfolio' : ''), 'good'];
      }
      if (state === 'absent') {
        return ['No ' + programLabel() + ' team has that number. The credit will read "Team ' +
                numberInput.value + '".', 'warn'];
      }
      if (state === 'invalid') return ['Team numbers run from 1 to 999999.', 'warn'];
      if (state === 'error') {
        return ['Could not reach the ' + programLabel() + ' registry. The number is enough — ' +
                'the name is filled in when you save.', 'warn'];
      }
      return ['', ''];
    }

    function ask(params, onDone) {
      var ticket = ++request;
      fetch(ENDPOINT + '?' + params + '&program=' + encodeURIComponent(program()), { headers: { Accept: 'application/json' } })
        .then(function (response) {
          return response.ok ? response.json() : { state: 'error', teams: [] };
        })
        .catch(function () { return { state: 'error', teams: [] }; })
        .then(function (data) { if (ticket === request) onDone(data); });
    }

    function resolveNumber() {
      var raw = (numberInput.value || '').trim();
      nameInput.value = '';
      showResults(null);
      if (!raw) { say(''); request++; return; }
      say('Looking up ' + raw + '…');
      ask('number=' + encodeURIComponent(raw), function (data) {
        var team = (data.teams || [])[0];
        if (team && String(team.number) === raw) nameInput.value = team.name;
        var told = describe(data.state, team);
        say(told[0], told[1]);
      });
    }

    function runSearch() {
      var query = (searchInput.value || '').trim();
      if (query.length < MIN_QUERY) {
        showResults(null);
        say(query ? 'Keep typing…' : '');
        request++;
        return;
      }
      say('Searching…');
      ask('q=' + encodeURIComponent(query), function (data) {
        showResults(data.teams);
        if (data.state === 'error') {
          say('Could not reach the ' + programLabel() + ' registry. Enter the number instead.', 'warn');
        } else if (!data.teams || !data.teams.length) {
          say('No teams match “' + query + '”.', 'warn');
        } else {
          say('Pick the team to credit.');
        }
      });
    }

    function setMode(mode) {
      var byName = mode === 'name';
      numberField.hidden = byName;
      nameField.hidden = !byName;
      toggle.textContent = byName ? 'Enter number' : 'Search by name';
      if (byName) {
        showResults(null);
        say('');
        searchInput.focus();
      }
    }

    function syncAttribution() {
      var isTeam = attribution.value === 'team';
      fields.hidden = !isTeam;
      numberInput.required = isTeam;
      if (!isTeam) {
        showResults(null);
        say('');
      }
    }

    toggle.addEventListener('click', function () {
      setMode(numberField.hidden ? 'number' : 'name');
    });

    numberInput.addEventListener('input', function () {
      window.clearTimeout(timer);
      nameInput.value = '';
      timer = window.setTimeout(resolveNumber, DEBOUNCE_MS);
    });

    searchInput.addEventListener('input', function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(runSearch, DEBOUNCE_MS);
    });

    // Enter in the search box means "search", not "submit the whole upload".
    searchInput.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      var first = results.hidden ? null : results.querySelector('.team-credit__result');
      if (first) { first.click(); return; }
      window.clearTimeout(timer);
      runSearch();
    });

    attribution.addEventListener('change', syncAttribution);
    if (programInput) programInput.addEventListener('change', function () {
      nameInput.value = '';
      if ((numberInput.value || '').trim()) resolveNumber();
    });
    syncAttribution();
    // An edit form arrives with a team already credited; confirm it on sight so
    // the admin can see whose number that is without having to touch the field.
    if (attribution.value === 'team' && (numberInput.value || '').trim()) resolveNumber();
  }

  function start() {
    var roots = document.querySelectorAll('[data-team-credit]');
    for (var i = 0; i < roots.length; i++) setup(roots[i]);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
