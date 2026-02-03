import Image from 'next/image'
import { login } from './actions'

type SearchParams = Record<string, string | string[] | undefined>

export default function LoginPage({ searchParams }: { searchParams?: SearchParams }) {
  const next =
    typeof searchParams?.next === 'string'
      ? searchParams?.next
      : Array.isArray(searchParams?.next)
        ? searchParams?.next[0]
        : '/'

  const error =
    typeof searchParams?.error === 'string'
      ? searchParams?.error
      : Array.isArray(searchParams?.error)
        ? searchParams?.error[0]
        : undefined

  const authEnabled = (process.env.PEARL_WEBAPP_AUTH_ENABLED || 'false').toLowerCase() === 'true'
  const hasPasscode = Boolean(process.env.PEARL_WEBAPP_PASSCODE)

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <Image src="/logo.png" alt="PEARL" width={42} height={42} className="login-logo" priority />
          <div className="login-titles">
            <div className="login-title">Pearl Algo</div>
            <div className="login-subtitle">Dashboard Access</div>
          </div>
        </div>

        {!authEnabled && (
          <div className="login-note">
            Auth is currently disabled. Set <code>PEARL_WEBAPP_AUTH_ENABLED=true</code> to enable passcode gating.
          </div>
        )}

        {authEnabled && !hasPasscode && (
          <div className="login-error">
            Server misconfigured: <code>PEARL_WEBAPP_PASSCODE</code> is not set.
          </div>
        )}

        {authEnabled && hasPasscode && (
          <form className="login-form" action={login}>
            <input type="hidden" name="next" value={next} />

            <label className="login-label" htmlFor="passcode">
              Passcode
            </label>
            <input
              id="passcode"
              name="passcode"
              type="password"
              className="login-input"
              autoFocus
              autoComplete="current-password"
              placeholder="Enter passcode"
            />

            {error === 'invalid' && (
              <div className="login-error">Wrong passcode.</div>
            )}
            {error === 'misconfigured' && (
              <div className="login-error">Auth is enabled but the server has no passcode configured.</div>
            )}

            <button className="login-button" type="submit">
              Unlock
            </button>

            <div className="login-hint">
              Tip: set the passcode in your local secrets file (not in git).
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

