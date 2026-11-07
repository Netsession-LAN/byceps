/* Swiss boards: lay out the record blocks and draw their connectors
   (public bracket page and admin stage view). */
(() => {
  const boards = Array.from(
    document.querySelectorAll('.ns-tourney-swiss-board')
  );
  if (!boards.length) {
    return;
  }

  const layoutSwissBoard = (board) => {
    const stage = board.querySelector('.ns-tourney-swiss-stage') || board;
    const gap = Number.parseFloat(
      getComputedStyle(board).getPropertyValue('--ns-swiss-block-gap')
    ) || 12;
    const getTopWithinStage = (element) => {
      let top = 0;
      let current = element;
      while (current && current !== stage) {
        top += current.offsetTop;
        current = current.offsetParent;
      }
      return top;
    };

    const columns = Array.from(
      stage.querySelectorAll('.ns-tourney-swiss-column')
    );
    const nodes = new Map();
    const incomingIdsByTargetId = new Map();

    columns.forEach((column, columnIndex) => {
      const body = column.querySelector('.ns-tourney-swiss-column-body');
      if (!body) {
        return;
      }

      const blocks = Array.from(
        body.querySelectorAll('[data-swiss-node-id]')
      );
      blocks.forEach((block, blockIndex) => {
        const nodeId = block.dataset.swissNodeId;
        nodes.set(nodeId, {
          element: block,
          body,
          columnIndex,
          blockIndex,
        });
      });
    });

    nodes.forEach(({ element }, nodeId) => {
      [element.dataset.swissWinnerTargetId, element.dataset.swissLoserTargetId]
        .filter(Boolean)
        .forEach((targetId) => {
          if (!incomingIdsByTargetId.has(targetId)) {
            incomingIdsByTargetId.set(targetId, []);
          }
          incomingIdsByTargetId.get(targetId).push(nodeId);
        });
    });

    const rowPositions = Array.from(nodes.values()).map(({ element }) =>
      Number.parseFloat(element.dataset.swissRowPosition || '0')
    );
    const minRowPosition = Math.min(...rowPositions);
    const maxRowPosition = Math.max(...rowPositions);
    const maxBlockHeight = Math.max(
      ...Array.from(nodes.values()).map(({ element }) => element.offsetHeight),
      54
    );
    const naturalBoardHeight = Math.max(
      ...columns.map((column) => {
        const body = column.querySelector('.ns-tourney-swiss-column-body');
        if (!body) {
          return 0;
        }
        const blocks = Array.from(body.querySelectorAll('[data-swiss-node-id]'));
        if (!blocks.length) {
          return 0;
        }
        return blocks.reduce((sum, block, index) => {
          return sum + block.offsetHeight + (index > 0 ? gap : 0);
        }, 0);
      }),
      maxBlockHeight
    );
    const rowSpan = Math.max(1, maxRowPosition - minRowPosition);
    const rowPitch = Math.max(
      maxBlockHeight * 0.3,
      naturalBoardHeight / (rowSpan + 6)
    );
    const baseCenter = maxBlockHeight / 2;
    const rowCenterFor = (rowPosition) =>
      baseCenter + ((rowPosition - minRowPosition) * rowPitch);
    const centerByNodeId = new Map();

    columns.forEach((column, columnIndex) => {
      const body = column.querySelector('.ns-tourney-swiss-column-body');
      if (!body) {
        return;
      }

      const blocks = Array.from(
        body.querySelectorAll('[data-swiss-node-id]')
      );

      const desiredBlocks = blocks.map((block, index) => {
        const rowPosition = Number.parseFloat(
          block.dataset.swissRowPosition || '0'
        );
        const incomingIds = incomingIdsByTargetId.get(block.dataset.swissNodeId) || [];
        const incomingCenters = incomingIds
          .map((sourceId) => centerByNodeId.get(sourceId))
          .filter((center) => Number.isFinite(center));
        const center = incomingCenters.length
          ? incomingCenters.reduce((sum, value) => sum + value, 0) / incomingCenters.length
          : rowCenterFor(rowPosition);
        return {
          block,
          index,
          rowPosition,
          height: block.offsetHeight,
          desiredCenter: center,
        };
      });

      desiredBlocks.sort((a, b) => {
        if (a.desiredCenter !== b.desiredCenter) {
          return a.desiredCenter - b.desiredCenter;
        }
        if (a.rowPosition !== b.rowPosition) {
          return a.rowPosition - b.rowPosition;
        }
        return a.index - b.index;
      });

      const centers = desiredBlocks.map((item) => item.desiredCenter);
      const targetGroupMidpoint = centers.length
        ? centers.reduce((sum, value) => sum + value, 0) / centers.length
        : 0;
      if (column.classList.contains('is-sidecar') && desiredBlocks.length === 2) {
        const anchorCenter =
          centers.reduce((sum, value) => sum + value, 0) / centers.length;
        const upper = desiredBlocks[0];
        const lower = desiredBlocks[1];
        centers[0] =
          anchorCenter - (gap / 2) - (lower.height / 2);
        centers[1] =
          anchorCenter + (gap / 2) + (upper.height / 2);
      }
      for (let pass = 0; pass < 10; pass += 1) {
        let changed = false;
        for (let i = 0; i < desiredBlocks.length - 1; i += 1) {
          const current = desiredBlocks[i];
          const next = desiredBlocks[i + 1];
          const dynamicGap =
            gap
            + Math.max(
              0,
              (((current.height + next.height) / 2) - 54) * 0.16
            );
          const minNextCenter =
            centers[i] +
            (current.height / 2) +
            dynamicGap +
            (next.height / 2);
          if (centers[i + 1] < minNextCenter) {
            const overlap = minNextCenter - centers[i + 1];
            centers[i] -= overlap / 2;
            centers[i + 1] += overlap / 2;
            changed = true;
          }
        }
        if (!changed) {
          break;
        }
      }

      if (!column.classList.contains('is-sidecar') && desiredBlocks.length > 1) {
        const minGroupTop = desiredBlocks.reduce((value, item, index) => {
          return Math.min(value, centers[index] - (item.height / 2));
        }, Number.POSITIVE_INFINITY);
        const maxGroupBottom = desiredBlocks.reduce((value, item, index) => {
          return Math.max(value, centers[index] + (item.height / 2));
        }, Number.NEGATIVE_INFINITY);
        const actualGroupMidpoint = (minGroupTop + maxGroupBottom) / 2;
        const midpointDelta = targetGroupMidpoint - actualGroupMidpoint;
        if (Number.isFinite(midpointDelta) && midpointDelta !== 0) {
          for (let i = 0; i < centers.length; i += 1) {
            centers[i] += midpointDelta;
          }
        }
      }

      const minTop = desiredBlocks.reduce((value, item, index) => {
        return Math.min(value, centers[index] - (item.height / 2));
      }, Number.POSITIVE_INFINITY);
      const shift = minTop < 0 ? -minTop : 0;

      desiredBlocks.forEach(({ block, height }, index) => {
        const top = centers[index] - (height / 2) + shift;
        block.style.top = `${Math.round(top)}px`;
        centerByNodeId.set(
          block.dataset.swissNodeId,
          top + (height / 2)
        );
      });

      const bodyHeight = blocks.reduce((maxBottom, block) => {
        const top = Number.parseFloat(block.style.top || '0') || 0;
        return Math.max(maxBottom, top + block.offsetHeight);
      }, 0);
      body.style.height = `${Math.max(128, Math.ceil(bodyHeight))}px`;
    });

    const allBlocks = Array.from(
      stage.querySelectorAll('[data-swiss-node-id]')
    );
    const globalMinTop = allBlocks.reduce((minimum, block) => {
      const top = Number.parseFloat(block.style.top || '0') || 0;
      return Math.min(minimum, top);
    }, Number.POSITIVE_INFINITY);

    const appliedShift =
      Number.isFinite(globalMinTop) && globalMinTop > 0 ? globalMinTop : 0;

    if (appliedShift > 0) {
      allBlocks.forEach((block) => {
        const top = Number.parseFloat(block.style.top || '0') || 0;
        block.style.top = `${Math.round(top - appliedShift)}px`;
      });
    }

    columns.forEach((column) => {
      if (!column.classList.contains('is-sidecar')) {
        return;
      }

      const body = column.querySelector('.ns-tourney-swiss-column-body');
      if (!body) {
        return;
      }

      const blocks = Array.from(
        body.querySelectorAll('[data-swiss-node-id]')
      );
      if (blocks.length !== 2) {
        return;
      }

      const sourceIds = Array.from(
        new Set(
          blocks.flatMap((block) =>
            incomingIdsByTargetId.get(block.dataset.swissNodeId) || []
          )
        )
      );
      const sourceCenters = sourceIds
        .map((sourceId) => nodes.get(sourceId)?.element)
        .filter(Boolean)
        .map((sourceElement) => {
          const top = getTopWithinStage(sourceElement);
          return top + (sourceElement.offsetHeight / 2);
        })
        .filter((center) => Number.isFinite(center));
      if (!sourceCenters.length) {
        return;
      }

      const roundPrefixMatch = blocks[0].dataset.swissNodeId.match(
        /^(swiss-round-\d+)-/
      );
      const explicitRoundAnchor = roundPrefixMatch
        ? stage.querySelector(
            `[data-swiss-node-id="${roundPrefixMatch[1]}-2-2"]`
          )
        : null;
      const anchorCenterInStage = explicitRoundAnchor
        ? getTopWithinStage(explicitRoundAnchor) +
          (explicitRoundAnchor.offsetHeight / 2)
        : sourceCenters.reduce((sum, value) => sum + value, 0) /
          sourceCenters.length;
      const bodyTopInStage = getTopWithinStage(body);
      const anchorCenter = anchorCenterInStage - bodyTopInStage;
      const sortedBlocks = blocks
        .slice()
        .sort((a, b) => {
          const aTop = Number.parseFloat(a.style.top || '0') || 0;
          const bTop = Number.parseFloat(b.style.top || '0') || 0;
          return aTop - bTop;
        });
      const upperBlock = sortedBlocks[0];
      const lowerBlock = sortedBlocks[1];
      const upperTop = anchorCenter - (gap / 2) - upperBlock.offsetHeight;
      const lowerTop = anchorCenter + (gap / 2);

      upperBlock.style.top = `${Math.round(upperTop)}px`;
      lowerBlock.style.top = `${Math.round(lowerTop)}px`;
    });

    columns.forEach((column) => {
      const body = column.querySelector('.ns-tourney-swiss-column-body');
      if (!body) {
        return;
      }

      const blocks = Array.from(
        body.querySelectorAll('[data-swiss-node-id]')
      );
      const bodyHeight = blocks.reduce((maxBottom, block) => {
        const top = Number.parseFloat(block.style.top || '0') || 0;
        return Math.max(maxBottom, top + block.offsetHeight);
      }, 0);
      body.style.height = `${Math.max(128, Math.ceil(bodyHeight))}px`;
    });
  };

  const drawSwissLines = (board) => {
    const stage = board.querySelector('.ns-tourney-swiss-stage') || board;
    const svg = stage.querySelector('.ns-tourney-swiss-lines');
    if (!svg) {
      return;
    }

    const nodes = new Map();
    const columns = Array.from(
      stage.querySelectorAll('.ns-tourney-swiss-column')
    );

    const boardWidth = Math.max(stage.scrollWidth, stage.clientWidth);
    const boardHeight = Math.max(stage.scrollHeight, stage.clientHeight);
    svg.setAttribute('width', String(boardWidth));
    svg.setAttribute('height', String(boardHeight));
    svg.setAttribute('viewBox', `0 0 ${boardWidth} ${boardHeight}`);
    svg.replaceChildren();

    const toBoardRect = (element) => {
      let left = 0;
      let top = 0;
      let current = element;
      while (current && current !== stage) {
        left += current.offsetLeft;
        top += current.offsetTop;
        current = current.offsetParent;
      }
      return {
        left,
        top,
        right: left + element.offsetWidth,
        bottom: top + element.offsetHeight,
        width: element.offsetWidth,
        height: element.offsetHeight,
      };
    };

    columns.forEach((column, columnIndex) => {
      column.querySelectorAll('[data-swiss-node-id]').forEach((element) => {
        nodes.set(element.dataset.swissNodeId, { element, columnIndex });
      });
    });

    stage.querySelectorAll('[data-swiss-winner-target-id], [data-swiss-loser-target-id]').forEach((source) => {
      const sourceRect = toBoardRect(source);
      const sourceNode = nodes.get(source.dataset.swissNodeId);
      const sourceTargets = [
        source.dataset.swissWinnerTargetId,
        source.dataset.swissLoserTargetId,
      ].filter(Boolean);

      sourceTargets.forEach((targetId) => {
        const targetNode = nodes.get(targetId);
        if (!targetNode || !sourceNode) {
          return;
        }

        const targetRect = toBoardRect(targetNode.element);
        const x1 = sourceRect.right;
        const y1 = sourceRect.top + (sourceRect.height / 2);
        const x2 = targetRect.left;
        const y2 = targetRect.top + (targetRect.height / 2);
        const xMidRaw = Math.round(
          x1 + ((x2 - x1) / 2)
        );
        const xMid = Math.max(x1 + 10, Math.min(x2 - 10, xMidRaw));

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'ns-tourney-swiss-line');
        path.setAttribute('d', `M ${x1} ${y1} H ${xMid} V ${y2} H ${x2}`);
        svg.append(path);
      });
    });
  };

  const redraw = () => {
    boards.forEach((board) => {
      layoutSwissBoard(board);
      drawSwissLines(board);
    });
  };

  window.addEventListener('resize', () => {
    window.requestAnimationFrame(redraw);
  });
  window.setTimeout(() => window.requestAnimationFrame(redraw), 160);
})();
