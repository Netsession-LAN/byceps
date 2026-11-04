self.addEventListener('push', (event) => {
  if (!event.data) {
    return;
  }

  const resolveAssetUrl = (rawUrl) => {
    if (!rawUrl) {
      return undefined;
    }

    return new URL(rawUrl, self.location.origin).href;
  };

  let payload = {};
  try {
    payload = event.data.json();
  } catch (_error) {
    payload = { title: 'Turnier-Update', body: event.data.text() };
  }

  const title = payload.title || 'Turnier-Update';
  const options = {
    body: payload.body || '',
    icon: resolveAssetUrl(payload.icon),
    badge: resolveAssetUrl(payload.badge || payload.icon),
    image: resolveAssetUrl(payload.image),
    tag: payload.tag || undefined,
    renotify: Boolean(payload.renotify),
    data: {
      url: payload.url || '/',
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const rawUrl = event.notification.data && event.notification.data.url
    ? event.notification.data.url
    : '/';
  const targetUrl = new URL(rawUrl, self.location.origin).href;

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }

      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }

      return undefined;
    })
  );
});
