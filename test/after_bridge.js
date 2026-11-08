// Test kit only: files the page saves (backup, Rory's PDF) are recorded instead of downloaded, like the kit's mock.js.
(() => {
  const use = window.claude.use;
  const downloads = {save: async x => { window.__saved.push({name: x.filename, size: x.data && x.data.size}); }};
  window.claude.use = name => name === 'downloads' ? Promise.resolve(downloads) : use(name);
})();
