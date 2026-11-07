/* One bracket canvas: positions the match cards per round, draws the
   connector lines, handles density and highlighting on hover. Called by
   bracket.js for every canvas (public bracket page and admin stage view). */
window.nsTourneyBracketCanvas = (canvas, api) => {
  const {
    bracket,
    canvases,
    getHighlightedParticipantId,
    highlightParticipantPath,
    setParticipantHighlight,
  } = api;

  const stage = canvas.querySelector('.ns-tourney-bracket-stage');
  const svg = canvas.querySelector('.ns-tourney-bracket-lines');
  const rounds = stage ? Array.from(stage.querySelectorAll('.ns-tourney-bracket-round')) : [];
  if (!stage || !rounds.length) {
    return;
  }

  const isFlatout2Bracket = stage.classList.contains(
    'ns-tourney-bracket-stage--flatout2'
  );

  const getPxVar = (name, fallback) => {
    const value = Number.parseFloat(
      getComputedStyle(stage).getPropertyValue(name)
    );
    return Number.isFinite(value) ? value : fallback;
  };

  const buildCardsByRound = () => {
    const cardsByRound = new Map();
    const cardsById = new Map();

    stage.querySelectorAll('.ns-tourney-bracket-match-card').forEach((card) => {
      if (card.dataset.matchId) {
        cardsById.set(card.dataset.matchId, card);
      }

      const roundIndex = Number.parseInt(card.dataset.roundIndex || '-1', 10);
      if (!Number.isFinite(roundIndex) || roundIndex < 0) {
        return;
      }

      if (!cardsByRound.has(roundIndex)) {
        cardsByRound.set(roundIndex, []);
      }
      cardsByRound.get(roundIndex).push(card);
    });

    cardsByRound.forEach((cards) => {
      cards.sort((a, b) => {
        const aIndex = Number.parseInt(a.dataset.roundMatchIndex || '0', 10);
        const bIndex = Number.parseInt(b.dataset.roundMatchIndex || '0', 10);
        return aIndex - bIndex;
      });
    });

    return { cardsByRound, cardsById };
  };

  const buildConnections = (cardsByRound, cardsById) => {
    const connections = [];
    const connectionKeys = new Set();

    const pushConnection = ({
      sourceMatchId,
      targetMatchId,
      sourceCard,
      targetCard,
      targetSlot,
    }) => {
      if (!sourceMatchId || !targetMatchId || !sourceCard || !targetCard) {
        return;
      }
      if (sourceMatchId === targetMatchId) {
        return;
      }

      const sourceRoundIndex = Number.parseInt(
        sourceCard.dataset.roundIndex || '-1',
        10
      );
      const targetRoundIndex = Number.parseInt(
        targetCard.dataset.roundIndex || '-1',
        10
      );
      if (
        Number.isFinite(sourceRoundIndex)
        && Number.isFinite(targetRoundIndex)
        && sourceRoundIndex >= targetRoundIndex
      ) {
        return;
      }

      const slotNo = targetSlot
        ? Number.parseInt(targetSlot.dataset.slotNo || '0', 10)
        : 0;
      const key = `${sourceMatchId}|${targetMatchId}|${slotNo}`;
      if (connectionKeys.has(key)) {
        return;
      }
      connectionKeys.add(key);

      connections.push({
        sourceMatchId,
        targetMatchId,
        sourceCard,
        targetCard,
        targetSlot,
      });
    };

    cardsByRound.forEach((cards, roundIndex) => {
      cards.forEach((targetCard, targetIndex) => {
        if (targetCard.dataset.noConnectors === 'true') {
          return;
        }

        const targetMatchId = targetCard.dataset.matchId;
        if (!targetMatchId) {
          return;
        }

        const targetSlots = Array.from(
          targetCard.querySelectorAll('.ns-tourney-bracket-slot')
        );
        const explicitSourceSlots = targetSlots.filter((slot) => slot.dataset.sourceMatchId);

        if (explicitSourceSlots.length) {
          let hasValidExplicitConnections = false;
          explicitSourceSlots.forEach((slot) => {
            const sourceMatchId = slot.dataset.sourceMatchId;
            const sourceCard = sourceMatchId
              ? cardsById.get(sourceMatchId) || null
              : null;
            const beforeCount = connections.length;
            pushConnection({
              sourceMatchId,
              targetMatchId,
              sourceCard,
              targetCard,
              targetSlot: slot,
            });
            if (connections.length > beforeCount) {
              hasValidExplicitConnections = true;
            }
          });
          if (hasValidExplicitConnections) {
            return;
          }
        }

        if (roundIndex <= 0) {
          return;
        }

        // Fallback for simple brackets if source links are not present.
        const previousRoundCards = cardsByRound.get(roundIndex - 1) || [];
        const sourceA = previousRoundCards[targetIndex * 2];
        const sourceB = previousRoundCards[targetIndex * 2 + 1];

        if (sourceA && sourceA.dataset.matchId) {
          pushConnection({
            sourceMatchId: sourceA.dataset.matchId,
            targetMatchId,
            sourceCard: sourceA,
            targetCard,
            targetSlot: targetSlots[0] || null,
          });
        }
        if (sourceB && sourceB.dataset.matchId) {
          pushConnection({
            sourceMatchId: sourceB.dataset.matchId,
            targetMatchId,
            sourceCard: sourceB,
            targetCard,
            targetSlot: targetSlots[1] || targetSlots[0] || null,
          });
        }
      });
    });

    return connections;
  };

  const positionCards = (cardsByRound, connections, metrics) => {
    const { cardHeight, rowGap, titleHeight, roundPadding, headerGap } = metrics;
    const firstRoundExtraGap = 2;
    const baseTop = titleHeight + roundPadding + headerGap;
    const topByCard = new Map();
    const targetConnectionsByCard = new Map();

    connections.forEach((connection) => {
      if (!targetConnectionsByCard.has(connection.targetCard)) {
        targetConnectionsByCard.set(connection.targetCard, []);
      }
      targetConnectionsByCard.get(connection.targetCard).push(connection);
    });

    const firstRoundCards = cardsByRound.get(0) || [];
    let topCursor = baseTop;
    firstRoundCards.forEach((card) => {
      topByCard.set(card, topCursor);
      topCursor += cardHeight + rowGap + firstRoundExtraGap;
    });

    for (let roundIndex = 1; roundIndex < rounds.length; roundIndex += 1) {
      const cards = cardsByRound.get(roundIndex) || [];
      let minTopForRound = baseTop;

      cards.forEach((card, index) => {
        const incomingConnections = targetConnectionsByCard.get(card) || [];
        const predecessorCenters = incomingConnections
          .map((connection) => connection.sourceCard)
          .filter(Boolean)
          .map((sourceCard) => topByCard.get(sourceCard))
          .filter((value) => Number.isFinite(value))
          .map((sourceTop) => sourceTop + (cardHeight / 2));

        let proposedTop;
        if (predecessorCenters.length > 0) {
          const averageCenter = predecessorCenters.reduce((sum, value) => sum + value, 0) / predecessorCenters.length;
          proposedTop = averageCenter - (cardHeight / 2);
        } else if (index === 0) {
          proposedTop = baseTop;
        } else {
          const previousCard = cards[index - 1];
          proposedTop = (topByCard.get(previousCard) || baseTop) + cardHeight + rowGap;
        }

        if (!Number.isFinite(proposedTop)) {
          proposedTop = baseTop;
        }
        if (proposedTop < minTopForRound) {
          proposedTop = minTopForRound;
        }

        topByCard.set(card, proposedTop);
        minTopForRound = proposedTop + cardHeight + rowGap;
      });
    }

    return topByCard;
  };

  const positionFlatout2Cards = (cardsByRound, metrics) => {
    const { cardHeight, rowGap, titleHeight, roundPadding, headerGap } = metrics;
    const firstRoundExtraGap = 2;
    const baseTop = titleHeight + roundPadding + headerGap;
    const topByCard = new Map();
    const firstRoundCards = cardsByRound.get(0) || [];

    let topCursor = baseTop;
    firstRoundCards.forEach((card) => {
      topByCard.set(card, topCursor);
      topCursor += cardHeight + rowGap + firstRoundExtraGap;
    });

    const firstRoundCount = firstRoundCards.length;
    const firstRoundSpan =
      firstRoundCount > 0
        ? cardHeight
          + ((firstRoundCount - 1) * (cardHeight + rowGap + firstRoundExtraGap))
        : cardHeight;
    const distributableSpan = Math.max(0, firstRoundSpan - cardHeight);

    for (let roundIndex = 1; roundIndex < rounds.length; roundIndex += 1) {
      const cards = cardsByRound.get(roundIndex) || [];
      if (!cards.length) {
        continue;
      }

      if (cards.length === 1) {
        topByCard.set(cards[0], baseTop + (distributableSpan / 2));
        continue;
      }

      const step = distributableSpan / (cards.length - 1);
      cards.forEach((card, index) => {
        topByCard.set(card, baseTop + (index * step));
      });
    }

    return {
      topByCard,
      stageHeight: baseTop + firstRoundSpan + roundPadding,
    };
  };

  const drawLines = (width, height, connections) => {
    if (!svg) {
      return;
    }

    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.replaceChildren();

    const stageRect = stage.getBoundingClientRect();
    const toStageRect = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left - stageRect.left,
        top: rect.top - stageRect.top,
        right: rect.right - stageRect.left,
        bottom: rect.bottom - stageRect.top,
        width: rect.width,
        height: rect.height,
      };
    };

    connections.forEach((connection) => {
      const sourceCard = connection.sourceCard;
      const targetCard = connection.targetCard;
      if (!sourceCard || !targetCard) {
        return;
      }

      const sourceRect = toStageRect(sourceCard);
      const targetRect = toStageRect(targetCard);
      const x1 = sourceRect.right;
      const y1 = sourceRect.top + (sourceRect.height / 2);

      // Draw connectors match-to-match for a clearer tournament tree.
      // Slightly overlap into the target card so the connector visually
      // closes flush with the card border (no tiny gap from anti-aliasing).
      const x2 = Math.max(0, targetRect.left);
      const y2 = targetRect.top + (targetRect.height / 2);

      const xMid = x1 + Math.max(12, (x2 - x1) * 0.5);

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'ns-tourney-bracket-line');
      path.dataset.sourceMatchId = connection.sourceMatchId;
      path.dataset.targetMatchId = connection.targetMatchId;
      path.setAttribute('d', `M ${x1} ${y1} H ${xMid} V ${y2} H ${x2}`);
      svg.append(path);
    });
  };

  const layoutBracket = () => {
    const roundWidthFromCss = getPxVar('--ns-round-width', 208);
    const roundCardGap = 20;
    const titleHeight = getPxVar('--ns-round-title-height', 30);
    const headerGap = getPxVar('--ns-round-header-gap', 12);
    const roundPadding = getPxVar('--ns-round-padding', 6);
    const cardMinHeight = getPxVar('--ns-card-min-height', 58);
    const cardHeightByDensity = getPxVar('--ns-card-height', cardMinHeight + 28);
    const rowGap = getPxVar('--ns-row-gap', 8);
    const cardInset = getPxVar('--ns-card-inset', 6);
    const cardInnerWidth = getPxVar('--ns-card-width', 150);
    const roundWidth = Math.max(
      roundWidthFromCss,
      cardInnerWidth + (cardInset * 2)
    );
    const cardOffsetX = Math.max(
      0,
      (roundWidth - cardInnerWidth) / 2
    );
    const roundStride = cardInnerWidth + roundCardGap;

    const cardHeight = cardHeightByDensity;
    const baseTop = titleHeight + roundPadding + headerGap;
    let stageHeight = baseTop + cardHeight + roundPadding;
    const { cardsByRound, cardsById } = buildCardsByRound();
    const connections = buildConnections(cardsByRound, cardsById);
    const positioning = isFlatout2Bracket
      ? positionFlatout2Cards(
          cardsByRound,
          { cardHeight, rowGap, titleHeight, roundPadding, headerGap }
        )
      : {
          topByCard: positionCards(
            cardsByRound,
            connections,
            { cardHeight, rowGap, titleHeight, roundPadding, headerGap }
          ),
          stageHeight: null,
        };
    const topByCard = positioning.topByCard;
    if (Number.isFinite(positioning.stageHeight)) {
      stageHeight = Math.max(stageHeight, positioning.stageHeight);
    }
    let maxCardRight = 0;

    rounds.forEach((round, roundIndex) => {
      const roundLeft = roundIndex * roundStride;
      round.style.left = `${roundLeft}px`;
      round.style.width = `${roundWidth}px`;

      const cards = Array.from(
        round.querySelectorAll('.ns-tourney-bracket-match-card')
      );
      const consolationCard = cards.find((card) => card.dataset.noConnectors === 'true') || null;
      const primaryFinalCard = cards.find((card) => card !== consolationCard) || null;
      const primaryFinalTop = primaryFinalCard ? topByCard.get(primaryFinalCard) : null;
      let nextTop = baseTop;

      cards.forEach((card) => {
        let cardLeft = cardOffsetX;
        // The match for third place goes below the final, same column.

        card.style.left = `${cardLeft}px`;
        card.style.right = 'auto';
        card.style.width = `${cardInnerWidth}px`;
        card.style.height = `${cardHeight}px`;
        let top = topByCard.get(card);
        if (card === consolationCard && Number.isFinite(primaryFinalTop)) {
          top = primaryFinalTop + (cardHeight * 1.5) + rowGap;
        }
        if (!Number.isFinite(top)) {
          top = nextTop;
        }
        card.style.top = `${top}px`;
        nextTop = top + cardHeight + rowGap;
        stageHeight = Math.max(stageHeight, top + cardHeight + roundPadding);
        maxCardRight = Math.max(
          maxCardRight,
          roundLeft + cardLeft + cardInnerWidth + cardOffsetX
        );
      });
    });

    const baseStageWidth = (
      rounds.length * cardInnerWidth
      + Math.max(0, rounds.length - 1) * roundCardGap
      + (roundWidth - cardInnerWidth)
    );
    const stageWidth = Math.max(baseStageWidth, maxCardRight);

    stage.style.width = `${stageWidth}px`;
    stage.style.height = `${stageHeight}px`;
    rounds.forEach((round) => {
      round.style.height = `${stageHeight}px`;
    });

    drawLines(stageWidth, stageHeight, connections);
    if (getHighlightedParticipantId()) {
      highlightParticipantPath(getHighlightedParticipantId());
    }
  };

  const setDensity = (density) => {
    stage.classList.remove(
      'is-density-ultra',
      'is-density-compact',
      'is-density-comfortable'
    );
    stage.classList.add(`is-density-${density}`);

    requestAnimationFrame(layoutBracket);
  };

  if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(layoutBracket);
    });
    resizeObserver.observe(canvas);
  }
  window.addEventListener('resize', () => {
    requestAnimationFrame(layoutBracket);
  });

  stage.addEventListener('pointermove', (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }

    const slot = event.target.closest('.ns-tourney-bracket-slot[data-participant-id]');
    setParticipantHighlight(slot?.dataset.participantId || null);
  });

  stage.addEventListener('pointerleave', () => {
    setParticipantHighlight(null);
  });

  stage.querySelectorAll('.ns-tourney-bracket-match-card').forEach((card) => {
    const url = card.dataset.matchUrl;

    if (!url) {
      return;
    }
    card.addEventListener('click', (event) => {
      event.preventDefault();
      window.location.href = url;
    });
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        window.location.href = url;
      }
    });
  });

  setDensity('comfortable');
  window.setTimeout(() => requestAnimationFrame(layoutBracket), 140);
};
