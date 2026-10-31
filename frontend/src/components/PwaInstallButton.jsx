import { useEffect, useState } from 'react'

function checkIsStandalone() {
  if (typeof window === 'undefined') return false
  return Boolean(
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator?.standalone
  )
}

function checkIsIOS() {
  if (typeof window === 'undefined') return false
  return /iphone|ipad|ipod/.test(window.navigator?.userAgent?.toLowerCase() || '')
}

export default function PwaInstallButton() {
  const [deferredPrompt, setDeferredPrompt] = useState(null)
  const [isInstalled, setIsInstalled] = useState(checkIsStandalone)
  const [isIOS] = useState(checkIsIOS)
  const [showIosTip, setShowIosTip] = useState(false)

  useEffect(() => {
    function handleBeforeInstallPrompt(e) {
      e.preventDefault()
      setDeferredPrompt(e)
    }

    function handleAppInstalled() {
      setIsInstalled(true)
      setDeferredPrompt(null)
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt)
    window.addEventListener('appinstalled', handleAppInstalled)

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt)
      window.removeEventListener('appinstalled', handleAppInstalled)
    }
  }, [])

  async function handleInstall() {
    if (deferredPrompt) {
      deferredPrompt.prompt()
      const { outcome } = await deferredPrompt.userChoice
      if (outcome === 'accepted') {
        setIsInstalled(true)
      }
      setDeferredPrompt(null)
    } else if (isIOS) {
      setShowIosTip((prev) => !prev)
    }
  }

  if (isInstalled) {
    return (
      <div className="pwa-badge installed" title="Running in Progressive Web App mode">
        <span className="pwa-dot" /> PWA Installed
      </div>
    )
  }

  return (
    <div className="pwa-install-container">
      <button
        type="button"
        className="pwa-install-btn"
        onClick={handleInstall}
        title="Install as Progressive Web App"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        <span>Install App</span>
      </button>

      {showIosTip && (
        <div className="ios-pwa-tip">
          Tap <strong>Share 📤</strong> then <strong>&quot;Add to Home Screen&quot;</strong> to install.
        </div>
      )}
    </div>
  )
}
