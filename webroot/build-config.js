/* Compiled test builds may enable READ-ONLY transport after the exact VM scope is approved.
 * This is a rollout gate, not an authority or privilege boundary. It never enables writes.
 */
window.GUIZANG_BUILD = Object.freeze({ deviceReadOnlyBridge: false });
