// The home-screen icon: Four pots, light or dark. iOS takes a web app's icon once, when it's added to the Home Screen,
// and can't swap it later, so the app hands over the version that matches the iPhone's look at that moment.
if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) document.querySelector('link[rel="apple-touch-icon"]').href = 'icon-dark-180.png';
