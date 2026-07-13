export class GatewayReauthRequiredError extends Error {
    needsOauthLogin = true;
    constructor(message, options) {
        super(message, options);
        this.name = 'GatewayReauthRequiredError';
    }
}
export function isGatewayReauthRequired(error) {
    return (error instanceof GatewayReauthRequiredError ||
        (typeof error === 'object' && error !== null && error.needsOauthLogin === true));
}
export async function resolveGatewayWsUrl(deps, conn) {
    const mint = deps.getGatewayWsUrl;
    const profile = conn.profile ?? null;
    if (conn.authMode === 'oauth') {
        if (!mint) {
            throw new GatewayReauthRequiredError('Your remote gateway session needs to be refreshed. Open Settings -> Gateway and click "Sign in" again.');
        }
        try {
            return await mint(profile);
        }
        catch (error) {
            throw new GatewayReauthRequiredError('Your remote gateway session has expired. Open Settings -> Gateway and click "Sign in" again.', { cause: error });
        }
    }
    if (mint) {
        const fresh = await mint(profile).catch(() => null);
        if (fresh) {
            return fresh;
        }
    }
    return conn.wsUrl;
}
function readWindowLocation() {
    if (typeof window === 'undefined') {
        return { host: '', protocol: 'http:' };
    }
    return { host: window.location.host, protocol: window.location.protocol };
}
function normalizeBasePath(basePath) {
    if (!basePath) {
        return '';
    }
    const withLead = basePath.startsWith('/') ? basePath : `/${basePath}`;
    return withLead.replace(/\/+$/, '');
}
function normalizeEndpointPath(path) {
    return path.startsWith('/') ? path : `/${path}`;
}
export function buildHermesWebSocketUrl(options) {
    const loc = readWindowLocation();
    const protocol = options.protocol ?? loc.protocol;
    const host = options.host ?? loc.host;
    const wsScheme = protocol === 'https:' || protocol === 'wss:' ? 'wss:' : 'ws:';
    const qs = new URLSearchParams(options.params ?? {});
    if (options.authParam) {
        const [name, value] = options.authParam;
        qs.set(name, value);
    }
    const query = qs.toString();
    const suffix = query ? `?${query}` : '';
    return `${wsScheme}//${host}${normalizeBasePath(options.basePath)}${normalizeEndpointPath(options.path)}${suffix}`;
}
