// NeuralMesh chat — notifications stub (v0.1): tab-title unread counter only
import { store } from './store.js';

const ORIGINAL_TITLE = 'NeuralMesh Beta';

export function mountNotifications() {
  store.subscribe(function(state) {
    const totalUnread = state.agents.reduce(function(acc, a) {
      return acc + (a.unread || 0);
    }, 0);
    document.title = totalUnread > 0
      ? '(' + totalUnread + ') ' + ORIGINAL_TITLE
      : ORIGINAL_TITLE;
  });
}
