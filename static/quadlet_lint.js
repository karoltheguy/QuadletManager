import { lintModel } from './vendor/quadlet-lint/monaco.js';

/**
 * Attach live quadlet-lint diagnostics to a Monaco model.
 *
 * Lints immediately on attach, then re-lints (debounced) on every
 * model.onDidChangeContent event. Never lints a disposed model. Returns a
 * detach() function that cancels any pending debounced lint and disposes
 * the content-change subscription.
 *
 * @param {object} monacoNs - the Monaco namespace (window.monaco)
 * @param {object} model - a Monaco text model
 * @param {{ delay?: number }} [options]
 * @returns {() => void} detach
 */
export function attachQuadletLint(monacoNs, model, options) {
  const delay = (options && options.delay) || 200;
  let timeoutHandle = null;

  function runLint() {
    if (model.isDisposed && model.isDisposed()) return;
    lintModel(monacoNs, model);
  }

  function scheduleLint() {
    if (timeoutHandle !== null) {
      clearTimeout(timeoutHandle);
    }
    timeoutHandle = setTimeout(function () {
      timeoutHandle = null;
      runLint();
    }, delay);
  }

  runLint();

  const subscription = model.onDidChangeContent(function () {
    scheduleLint();
  });

  return function detach() {
    if (timeoutHandle !== null) {
      clearTimeout(timeoutHandle);
      timeoutHandle = null;
    }
    if (subscription && subscription.dispose) {
      subscription.dispose();
      subscription.dispose = function () {};
    }
  };
}
