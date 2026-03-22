/**
 * Simple OAuth Login/Consent Service for E2E Testing
 *
 * This service automatically accepts login and consent requests from Hydra
 * to enable deterministic OAuth flows in E2E tests.
 */

const express = require('express');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 3002;
const HYDRA_ADMIN_URL = process.env.HYDRA_ADMIN_URL || 'http://localhost:4447';

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'oauth-login-consent' });
});

// Login endpoint - auto-accept for test user
app.get('/login', async (req, res) => {
  const { login_challenge } = req.query;

  if (!login_challenge) {
    return res.status(400).json({ error: 'Missing login_challenge' });
  }

  try {
    console.log('🔐 [Login] Processing login challenge:', login_challenge);

    // Get login request details
    const loginRequest = await axios.get(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login`,
      { params: { login_challenge } }
    );

    console.log('🔐 [Login] Login request details:', {
      client_id: loginRequest.data.client?.client_id,
      subject: loginRequest.data.subject,
      requested_scope: loginRequest.data.requested_scope
    });

    // Auto-accept login for test user
    const acceptResponse = await axios.put(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login/accept`,
      {
        subject: 'test-user-id', // Test user ID
        remember: false,
        remember_for: 0,
        context: {
          email: 'test@example.com',
          name: 'Test User',
          provider: 'generic'
        }
      },
      { params: { login_challenge } }
    );

    console.log('🔐 [Login] Login accepted, redirecting to:', acceptResponse.data.redirect_to);

    // Redirect to Hydra's consent flow
    res.redirect(acceptResponse.data.redirect_to);

  } catch (error) {
    console.error('🔐 [Login] Error processing login:', JSON.stringify(error.response?.data || error.message));
    res.status(500).json({
      error: 'Login processing failed',
      details: error.response?.data || error.message
    });
  }
});

// Consent endpoint - auto-accept for test scenarios
app.get('/consent', async (req, res) => {
  const { consent_challenge } = req.query;

  if (!consent_challenge) {
    return res.status(400).json({ error: 'Missing consent_challenge' });
  }

  try {
    console.log('🔐 [Consent] Processing consent challenge:', consent_challenge);

    // Get consent request details
    const consentRequest = await axios.get(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent`,
      { params: { consent_challenge } }
    );

    console.log('🔐 [Consent] Consent request details:', {
      client_id: consentRequest.data.client?.client_id,
      subject: consentRequest.data.subject,
      requested_scope: consentRequest.data.requested_scope
    });

    // Auto-accept consent with requested scopes
    const acceptResponse = await axios.put(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/accept`,
      {
        grant_scope: consentRequest.data.requested_scope,
        grant_access_token_audience: consentRequest.data.requested_access_token_audience,
        remember: false,
        remember_for: 0,
        session: {
          id_token: {
            email: 'test@example.com',
            name: 'Test User',
            provider: 'generic'
          },
          userinfo: {
            email: 'test@example.com',
            name: 'Test User',
            provider: 'generic'
          }
        }
      },
      { params: { consent_challenge } }
    );

    console.log('🔐 [Consent] Consent accepted, redirecting to:', acceptResponse.data.redirect_to);

    // Redirect back to the application
    res.redirect(acceptResponse.data.redirect_to);

  } catch (error) {
    console.error('🔐 [Consent] Error processing consent:', JSON.stringify(error.response?.data || error.message));
    res.status(500).json({
      error: 'Consent processing failed',
      details: error.response?.data || error.message
    });
  }
});

// Logout endpoint - auto-accept logout
app.get('/logout', async (req, res) => {
  const { logout_challenge } = req.query;

  if (!logout_challenge) {
    return res.status(400).json({ error: 'Missing logout_challenge' });
  }

  try {
    console.log('🔐 [Logout] Processing logout challenge:', logout_challenge);

    // Auto-accept logout
    const acceptResponse = await axios.put(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/logout/accept`,
      {},
      { params: { logout_challenge } }
    );

    console.log('🔐 [Logout] Logout accepted, redirecting to:', acceptResponse.data.redirect_to);

    // Redirect to logout completion
    res.redirect(acceptResponse.data.redirect_to);

  } catch (error) {
    console.error('🔐 [Logout] Error processing logout:', error.message);
    res.status(500).json({
      error: 'Logout processing failed',
      details: error.response?.data || error.message
    });
  }
});

// Start server
app.listen(PORT, () => {
  console.log(`🔐 OAuth Login/Consent Service running on port ${PORT}`);
  console.log(`🔗 Hydra Admin URL: ${HYDRA_ADMIN_URL}`);
  console.log('🧪 Auto-accepting all login/consent requests for E2E testing');
});
