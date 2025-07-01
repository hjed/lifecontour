const express = require('express');
const axios = require('axios');
const bodyParser = require('body-parser');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3001;
const HYDRA_ADMIN_URL = process.env.HYDRA_ADMIN_URL || 'http://oauth-provider:4445';

// Middleware
app.use(cors());
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(express.static('public'));
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Test users for development
const TEST_USERS = [
  {
    id: 'dev-user-1',
    email: 'dev@example.com',
    name: 'Dev User',
    password: 'password123'
  },
  {
    id: 'test-user-1',
    email: 'test@example.com',
    name: 'Test User',
    password: 'test123'
  }
];

// Home page
app.get('/', (req, res) => {
  res.render('index', {
    title: 'OAuth2 Development Provider',
    users: TEST_USERS,
    hydraUrl: HYDRA_ADMIN_URL
  });
});

// Login page
app.get('/login', async (req, res) => {
  const { login_challenge } = req.query;

  if (!login_challenge) {
    return res.status(400).send('Missing login_challenge');
  }

  try {
    // Get login request info from Hydra
    const response = await axios.get(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login`, {
      params: { login_challenge }
    });

    res.render('login', {
      title: 'Login - OAuth2 Dev Provider',
      challenge: login_challenge,
      client: response.data.client,
      users: TEST_USERS
    });
  } catch (error) {
    console.error('Error getting login request:', error.message);
    res.status(500).send('Error processing login request');
  }
});

// Handle login form submission
app.post('/login', async (req, res) => {
  const { login_challenge, email, password } = req.body;

  // Find user
  const user = TEST_USERS.find(u => u.email === email && u.password === password);

  if (!user) {
    return res.render('login', {
      title: 'Login - OAuth2 Dev Provider',
      challenge: login_challenge,
      error: 'Invalid credentials',
      users: TEST_USERS
    });
  }

  try {
    // Accept login request
    const response = await axios.put(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login/accept`, {
      subject: user.id,
      remember: true,
      remember_for: 3600,
      context: {
        email: user.email,
        name: user.name
      }
    }, {
      params: { login_challenge }
    });

    res.redirect(response.data.redirect_to);
  } catch (error) {
    console.error('Error accepting login:', error.message);
    res.status(500).send('Error processing login');
  }
});

// Consent page
app.get('/consent', async (req, res) => {
  const { consent_challenge } = req.query;

  if (!consent_challenge) {
    return res.status(400).send('Missing consent_challenge');
  }

  try {
    // Get consent request info from Hydra
    const response = await axios.get(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent`, {
      params: { consent_challenge }
    });

    const consentRequest = response.data;

    res.render('consent', {
      title: 'Consent - OAuth2 Dev Provider',
      challenge: consent_challenge,
      client: consentRequest.client,
      user: consentRequest.subject,
      scopes: consentRequest.requested_scope
    });
  } catch (error) {
    console.error('Error getting consent request:', error.message);
    res.status(500).send('Error processing consent request');
  }
});

// Handle consent form submission
app.post('/consent', async (req, res) => {
  const { consent_challenge, grant } = req.body;

  try {
    if (grant === 'allow') {
      // Accept consent
      const consentResponse = await axios.get(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent`, {
        params: { consent_challenge }
      });

      const response = await axios.put(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/accept`, {
        grant_scope: consentResponse.data.requested_scope,
        grant_access_token_audience: consentResponse.data.requested_access_token_audience,
        session: {
          id_token: {
            email: 'dev@example.com',
            name: 'Dev User'
          }
        }
      }, {
        params: { consent_challenge }
      });

      res.redirect(response.data.redirect_to);
    } else {
      // Reject consent
      const response = await axios.put(`${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/reject`, {
        error: 'access_denied',
        error_description: 'User denied access'
      }, {
        params: { consent_challenge }
      });

      res.redirect(response.data.redirect_to);
    }
  } catch (error) {
    console.error('Error processing consent:', error.message);
    res.status(500).send('Error processing consent');
  }
});

// API endpoint to create OAuth client
app.post('/api/clients', async (req, res) => {
  try {
    const client = {
      client_id: 'dev-client-id',
      client_secret: 'dev-client-secret',
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      scope: 'openid profile email',
      redirect_uris: ['http://localhost:3000/auth/callback'],
      token_endpoint_auth_method: 'client_secret_post'
    };

    const response = await axios.post(`${HYDRA_ADMIN_URL}/admin/clients`, client);
    res.json(response.data);
  } catch (error) {
    console.error('Error creating client:', error.message);
    res.status(500).json({ error: 'Failed to create client' });
  }
});

app.listen(PORT, () => {
  console.log(`🔐 OAuth2 Development UI running on http://localhost:${PORT}`);
  console.log(`🔧 Hydra Admin URL: ${HYDRA_ADMIN_URL}`);

  // Auto-create development client
  setTimeout(async () => {
    try {
      await axios.post(`http://localhost:${PORT}/api/clients`);
      console.log('✅ Development OAuth client created');
    } catch (error) {
      console.log('ℹ️  OAuth client may already exist');
    }
  }, 5000);
});
