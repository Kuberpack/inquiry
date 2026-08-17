// Vercel Edge Middleware — HTTP Basic Auth gate for the whole dashboard.
// Runs on Vercel only (ignored by `vite dev`/`vite preview`), before any
// static file is served. Set BASIC_AUTH_USER and BASIC_AUTH_PASS as
// environment variables in the Vercel project settings.

export const config = {
  matcher: '/:path*',
}

function unauthorized() {
  return new Response('Authentication required.', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="Kuberpack Enquiry Log"' },
  })
}

export default function middleware(request) {
  const expectedUser = process.env.BASIC_AUTH_USER
  const expectedPass = process.env.BASIC_AUTH_PASS

  if (!expectedUser || !expectedPass) {
    // Misconfigured — fail closed rather than serving the dashboard unprotected.
    return unauthorized()
  }

  const authHeader = request.headers.get('authorization')
  if (!authHeader || !authHeader.startsWith('Basic ')) {
    return unauthorized()
  }

  const decoded = atob(authHeader.slice('Basic '.length))
  const separatorIndex = decoded.indexOf(':')
  const user = decoded.slice(0, separatorIndex)
  const pass = decoded.slice(separatorIndex + 1)

  if (user !== expectedUser || pass !== expectedPass) {
    return unauthorized()
  }
}
