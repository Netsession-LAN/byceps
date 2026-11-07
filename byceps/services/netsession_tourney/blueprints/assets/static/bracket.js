/* Bracket view: fullscreen toggle, participant highlighting, and the
   bracket canvases (drawn by bracket_canvas.js, loaded before). */
(() => {
  const bracketView = document.querySelector('.ns-tourney-bracket-view');
  if (!bracketView) {
    return;
  }

  const bracket = bracketView.querySelector('.ns-tourney-bracket');
  if (!bracket) {
    return;
  }

  const fullscreenToggle = bracket.querySelector(
    '[data-action="toggle-bracket-fullscreen"]'
  );
  const canvases = Array.from(
    bracket.querySelectorAll('.ns-tourney-bracket-canvas')
  );
  const swissBoards = Array.from(
    bracket.querySelectorAll('.ns-tourney-swiss-board')
  );
  if (!canvases.length && !swissBoards.length) {
    return;
  }

  const isBracketExpanded = () =>
    bracketView.classList.contains('is-expanded');
  const updateFullscreenUi = () => {
    if (!fullscreenToggle) {
      return;
    }

    const expanded = isBracketExpanded();
    bracket.classList.toggle('is-fullscreen', expanded);
    fullscreenToggle.setAttribute('aria-pressed', expanded ? 'true' : 'false');
  };
  const setBracketExpanded = (expanded) => {
    bracketView.classList.toggle('is-expanded', expanded);
    document.body.classList.toggle('ns-tourney-bracket-expanded', expanded);
    updateFullscreenUi();
    window.dispatchEvent(new Event('resize'));
  };
  if (fullscreenToggle) {
    fullscreenToggle.hidden = false;
    fullscreenToggle.addEventListener('click', (event) => {
      event.preventDefault();
      setBracketExpanded(!isBracketExpanded());
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isBracketExpanded()) {
        setBracketExpanded(false);
      }
    });
    updateFullscreenUi();
  }

  let highlightedParticipantId = null;
  const clearHighlights = () => {
    bracket
      .querySelectorAll(
        '.ns-tourney-bracket-slot.is-highlighted, .ns-tourney-swiss-match-slot.is-highlighted, .ns-tourney-swiss-outcome-entry.is-highlighted'
      )
      .forEach((slot) => {
        slot.classList.remove('is-highlighted');
      });
  };
  const highlightParticipantPath = (participantId) => {
    clearHighlights();
    if (!participantId) {
      return;
    }
    bracket
      .querySelectorAll(
        `.ns-tourney-bracket-slot[data-participant-id="${participantId}"], .ns-tourney-swiss-match-slot[data-participant-id="${participantId}"], .ns-tourney-swiss-outcome-entry[data-participant-id="${participantId}"]`
      )
      .forEach((slot) => {
        slot.classList.add('is-highlighted');
      });
  };
  const setParticipantHighlight = (participantId) => {
    const normalized = participantId || null;
    if (normalized === highlightedParticipantId) {
      return;
    }
    highlightedParticipantId = normalized;
    if (!normalized) {
      clearHighlights();
      return;
    }
    highlightParticipantPath(normalized);
  };

  canvases.forEach((canvas) => {
    window.nsTourneyBracketCanvas(canvas, {
      bracket,
      canvases,
      getHighlightedParticipantId: () => highlightedParticipantId,
      highlightParticipantPath,
      setParticipantHighlight,
    });
  });

  swissBoards.forEach((board) => {
    board.addEventListener('pointermove', (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }

      const slot = event.target.closest(
        '.ns-tourney-swiss-match-slot[data-participant-id], .ns-tourney-swiss-outcome-entry[data-participant-id]'
      );
      setParticipantHighlight(slot?.dataset.participantId || null);
    });

    board.addEventListener('pointerleave', () => {
      setParticipantHighlight(null);
    });
  });
})();
