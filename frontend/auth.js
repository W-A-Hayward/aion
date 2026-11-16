// Username + password accounts on an Amazon Cognito user pool, called directly with fetch (no SDK, no build).
// Sign-in uses USER_PASSWORD_AUTH over HTTPS to Cognito; the password never reaches the AION backend.
// The session (ID, access and refresh tokens) is kept in this browser so a returning user stays signed in.
import { config } from './config.js';

export const SESSION_KEY = 'aion.auth.v1';
export const PASSWORD_MIN = 8;
export const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/;

export const authConfigured = (settings = config) => Boolean(settings.auth?.userPoolId && settings.auth?.clientId && settings.userDataUrl);

const MESSAGES = {
  NotAuthorizedException: 'Wrong username or password.',
  UserNotFoundException: 'Wrong username or password.',
  UsernameExistsException: 'That username is taken. Choose another one.',
  InvalidPasswordException: `Use a password of at least ${PASSWORD_MIN} characters.`,
  TooManyRequestsException: 'Too many attempts. Wait a moment and try again.',
  LimitExceededException: 'Too many attempts. Wait a moment and try again.',
  UserNotConfirmedException: 'This account is not confirmed yet. Contact the team.',
  PasswordResetRequiredException: 'This account needs a password reset. Contact the team.',
};

export class AuthError extends Error {
  constructor(code, message) { super(message); this.name = 'AuthError'; this.code = code; }
}

/** Validate before calling Cognito, so the user gets an immediate, specific message. */
export function checkCredentials(username, password) {
  if (!USERNAME_RE.test(username ?? '')) return 'Usernames are 3–32 characters: letters, numbers, dot, dash or underscore.';
  if (typeof password !== 'string' || password.length < PASSWORD_MIN) return `Use a password of at least ${PASSWORD_MIN} characters.`;
  if (password.length > 256) return 'That password is too long.';
  return null;
}

/** Payload of a JWT (no signature check: the API Gateway authorizer verifies tokens; this only reads claims). */
export function jwtClaims(token) {
  try {
    const part = String(token).split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(part + '='.repeat((4 - (part.length % 4)) % 4));
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0))));
  } catch { return {}; }
}

export function createAuth(settings = config, transport = globalThis.fetch, storage = globalThis.localStorage, now = Date.now) {
  const endpoint = () => `https://cognito-idp.${settings.auth.region}.amazonaws.com/`;
  const call = async (action, body) => {
    let response;
    try {
      response = await transport(endpoint(), { method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${action}` },
        body: JSON.stringify(body) });
    } catch { throw new AuthError('Network', 'Couldn’t reach the sign-in service. Check your connection.'); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = String(data.__type ?? '').split('#').pop() || `HTTP${response.status}`;
      let message = MESSAGES[code];
      if (!message && code === 'UserLambdaValidationException') message = String(data.message ?? '').replace(/^PreSignUp failed with error\s*/i, '').replace(/\.?$/, '.');
      throw new AuthError(code, message || 'Sign-in failed. Try again.');
    }
    return data;
  };
  const read = () => { try { const s = JSON.parse(storage?.getItem(SESSION_KEY) ?? 'null'); return s?.idToken && s?.refreshToken ? s : null; } catch { return null; } };
  const write = s => { try { if (s) storage?.setItem(SESSION_KEY, JSON.stringify(s)); else storage?.removeItem(SESSION_KEY); } catch {} };
  const fromResult = (result, previous = {}) => {
    const claims = jwtClaims(result.IdToken);
    return { idToken: result.IdToken, accessToken: result.AccessToken, refreshToken: result.RefreshToken ?? previous.refreshToken,
      expiresAt: now() + (Number(result.ExpiresIn) || 3600) * 1000,
      sub: claims.sub ?? previous.sub, username: claims['cognito:username'] ?? previous.username };
  };
  let session = read(), refreshing = null;

  const api = {
    configured: () => authConfigured(settings),
    session: () => (session ? { username: session.username, sub: session.sub } : null),
    async signIn(username, password) {
      const problem = checkCredentials(username, password);
      if (problem) throw new AuthError('Invalid', problem);
      const data = await call('InitiateAuth', { AuthFlow: 'USER_PASSWORD_AUTH', ClientId: settings.auth.clientId,
        AuthParameters: { USERNAME: username, PASSWORD: password } });
      if (!data.AuthenticationResult) throw new AuthError(data.ChallengeName ?? 'Challenge', 'This account needs an extra sign-in step that AION does not support.');
      session = fromResult(data.AuthenticationResult);
      write(session);
      return api.session();
    },
    async signUp(username, password) {
      const problem = checkCredentials(username, password);
      if (problem) throw new AuthError('Invalid', problem);
      await call('SignUp', { ClientId: settings.auth.clientId, Username: username, Password: password });
      return api.signIn(username, password);   // accounts are confirmed at sign-up (lambdas/presignup)
    },
    /** A valid ID token for the user-data API, refreshed shortly before it expires. */
    async idToken() {
      if (!session) throw new AuthError('SignedOut', 'Sign in again.');
      if (session.expiresAt - now() > 60_000) return session.idToken;
      refreshing ??= call('InitiateAuth', { AuthFlow: 'REFRESH_TOKEN_AUTH', ClientId: settings.auth.clientId,
        AuthParameters: { REFRESH_TOKEN: session.refreshToken } })
        .then(data => { session = fromResult(data.AuthenticationResult, session); write(session); return session.idToken; })
        .catch(error => { if (error.code === 'NotAuthorizedException') { session = null; write(null); throw new AuthError('SignedOut', 'Your session ended. Sign in again.'); } throw error; })
        .finally(() => { refreshing = null; });
      return refreshing;
    },
    async changePassword(previous, proposed) {
      const problem = checkCredentials(session?.username ?? 'xxx', proposed);
      if (problem) throw new AuthError('Invalid', problem);
      await api.idToken();
      await call('ChangePassword', { PreviousPassword: previous, ProposedPassword: proposed, AccessToken: session.accessToken });
    },
    /** Ends this browser's session; the refresh token is revoked so it cannot be reused. */
    async signOut() {
      const s = session;
      session = null; write(null);
      if (s?.refreshToken) await call('RevokeToken', { Token: s.refreshToken, ClientId: settings.auth.clientId }).catch(() => {});
    },
    /** Deletes the Cognito user. Call after the user's stored data was deleted. */
    async deleteUser() {
      await api.idToken();
      await call('DeleteUser', { AccessToken: session.accessToken });
      session = null; write(null);
    },
  };
  return api;
}
