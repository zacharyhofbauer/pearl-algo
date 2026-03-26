// Unregister self immediately — PWA disabled
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', () => {
  self.registration.unregister()
  clients.matchAll({ type: 'window' }).then(cs => cs.forEach(c => c.navigate(c.url)))
})
