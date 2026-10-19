// =========================================================================
// SERVIQO AI — FRONTEND APPLICATION CONTROLLER
// Intelligent Canteen Management, Demand Forecasting & Food Recovery Platform
// Primary Organization: Srinivas Institute Canteen / Kitchen
// Secondary Actor: Registered NGO / Relief Partner
// =========================================================================

// Dynamic API Base URL supporting cloud deployment, same-origin hosting, and local development
function getApiBase() {
    if (typeof window !== 'undefined' && window.__SERVIQO_API_URL__) {
        return window.__SERVIQO_API_URL__.replace(/\/$/, '');
    }
    if (typeof window !== 'undefined' && window.localStorage && localStorage.getItem('SERVIQO_API_URL')) {
        return localStorage.getItem('SERVIQO_API_URL').replace(/\/$/, '');
    }
    if (typeof window !== 'undefined' && window.location && (window.location.protocol === 'http:' || window.location.protocol === 'https:')) {
        // When frontend is served directly by the backend server or behind a reverse proxy
        return window.location.origin;
    }
    return 'http://127.0.0.1:8000';
}
const API_BASE = getApiBase();

// Global Application State
let currentMealTab = 'breakfast';
let cachedInventory = [];
let cachedSurplus = [];
let cachedNgos = [];
let cachedSuppliers = [];
let cachedDonations = [];
let cachedAnnouncements = [];
let cachedCanteenKpis = null;
let cachedNgoKpis = null;

// Chart Instances
let supplierDemandChartInstance = null;
let canteenAnalyticsDemandChartInstance = null;
let ngoRecoveryChartInstance = null;

// =========================================================================
// 1. AUTHENTICATION & SESSION PERSISTENCE
// =========================================================================

function getAuth() {
    try {
        const raw = sessionStorage.getItem('serviqo_auth');
        return raw ? JSON.parse(raw) : null;
    } catch (e) {
        return null;
    }
}

function setAuth(user) {
    if (user) {
        sessionStorage.setItem('serviqo_auth', JSON.stringify(user));
    } else {
        sessionStorage.removeItem('serviqo_auth');
    }
    syncUserInterface();
}

function authFetch(url, options = {}) {
    const auth = getAuth();
    const opts = { ...options };
    opts.headers = { ...(opts.headers || {}) };
    if (auth && auth.email) {
        opts.headers['X-User-Email'] = auth.email;
    }
    return fetch(url, opts);
}

function isCanteenRole(role) {
    if (!role) return false;
    const r = role.toLowerCase();
    return r.includes('kitchen') || r.includes('canteen') || r.includes('staff') || r.includes('supplier');
}

function isNgoRole(role) {
    if (!role) return false;
    const r = role.toLowerCase();
    return r.includes('ngo') || r.includes('relief') || r.includes('partner') || r.includes('shelter');
}

function syncUserInterface() {
    const auth = getAuth();
    const canteenNav = document.getElementById('canteen-sidebar-nav');
    const ngoNav = document.getElementById('ngo-sidebar-nav');
    const roleBadge = document.getElementById('header-role-badge');
    const userName = document.getElementById('header-user-name');
    const userSub = document.getElementById('header-user-sub');
    const avatarInitials = document.getElementById('header-avatar-initials');
    const orgPill = document.getElementById('header-organization-pill');
    const orgName = document.getElementById('header-org-name');
    const todayBadge = document.getElementById('today-date-badge');

    // Dropdown elements
    const dropName = document.getElementById('dropdown-user-name');
    const dropEmail = document.getElementById('dropdown-user-email');
    const dropRole = document.getElementById('dropdown-user-role');
    const dropAvatar = document.getElementById('dropdown-avatar-initials');

    // Update real-world date badge
    if (todayBadge) {
        const now = new Date();
        todayBadge.textContent = now.toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    }

    if (!auth) {
        // Logged-out Guest State
        if (canteenNav) canteenNav.classList.add('hidden');
        if (ngoNav) ngoNav.classList.add('hidden');
        if (roleBadge) {
            roleBadge.className = 'role-badge-pill';
            roleBadge.innerHTML = `<i class="ph ph-lock"></i> <span id="header-role-name">Authentication</span>`;
        }
        if (userName) userName.textContent = 'Guest';
        if (userSub) userSub.textContent = 'Not signed in';
        if (avatarInitials) avatarInitials.textContent = '?';
        if (orgPill) orgPill.classList.add('hidden');

        if (dropName) dropName.textContent = 'Guest';
        if (dropEmail) dropEmail.textContent = 'Not signed in';
        if (dropRole) {
            dropRole.className = 'badge badge-secondary';
            dropRole.textContent = 'Guest';
        }
        if (dropAvatar) dropAvatar.textContent = '?';
        return;
    }

    // Authenticated State: Populate Header & Dropdown
    const userRoleStr = isCanteenRole(auth.role) ? 'Kitchen Staff' : 'NGO / Relief Partner';
    const userOrgStr = auth.organization || (isCanteenRole(auth.role) ? 'Srinivas Institute Canteen' : 'Relief Partner');
    const userInitial = (auth.name || 'U').charAt(0).toUpperCase();

    if (orgPill && orgName) {
        orgPill.classList.remove('hidden');
        orgName.textContent = userOrgStr;
    }

    if (userName) userName.textContent = auth.name || 'User';
    if (userSub) userSub.textContent = userRoleStr;
    if (avatarInitials) avatarInitials.textContent = userInitial;

    if (dropName) dropName.textContent = auth.name || 'User';
    if (dropEmail) dropEmail.textContent = auth.email || '';
    if (dropRole) {
        dropRole.className = isCanteenRole(auth.role) ? 'badge badge-success' : 'badge badge-warning';
        dropRole.textContent = userRoleStr;
    }
    if (dropAvatar) dropAvatar.textContent = userInitial;

    if (isCanteenRole(auth.role)) {
        if (canteenNav) canteenNav.classList.remove('hidden');
        if (ngoNav) ngoNav.classList.add('hidden');
        if (roleBadge) {
            roleBadge.className = 'role-badge-pill';
            roleBadge.innerHTML = `<i class="ph ph-storefront"></i> <span id="header-role-name">Canteen Staff</span>`;
        }

        // Update Canteen Profile view data
        const profName = document.getElementById('canteen-profile-name');
        const profEmail = document.getElementById('canteen-profile-email');
        const profRole = document.getElementById('canteen-profile-role');
        const profOrg = document.getElementById('canteen-profile-org');
        if (profName) profName.textContent = auth.name || 'Kitchen Staff';
        if (profEmail) profEmail.textContent = auth.email;
        if (profRole) profRole.textContent = auth.role || 'Kitchen Staff';
        if (profOrg) profOrg.textContent = userOrgStr;

        // Dynamic Canteen Greeting
        const greetName = document.getElementById('canteen-home-greeting-name');
        if (greetName) greetName.textContent = auth.name || 'Kitchen Staff';

    } else {
        // NGO Role
        if (canteenNav) canteenNav.classList.add('hidden');
        if (ngoNav) ngoNav.classList.remove('hidden');
        if (roleBadge) {
            roleBadge.className = 'role-badge-pill ngo';
            roleBadge.innerHTML = `<i class="ph ph-heart"></i> <span id="header-role-name">NGO Partner</span>`;
        }

        // Update NGO Profile view data
        const profName = document.getElementById('ngo-profile-name');
        const profEmail = document.getElementById('ngo-profile-email');
        const profOrg = document.getElementById('ngo-profile-org');
        const profRole = document.getElementById('ngo-profile-role');
        if (profName) profName.textContent = auth.name || 'Relief Partner';
        if (profEmail) profEmail.textContent = auth.email;
        if (profOrg) profOrg.textContent = userOrgStr;
        if (profRole) profRole.textContent = auth.role || 'Registered NGO Partner';

        // Dynamic NGO Greeting
        const greetName = document.getElementById('ngo-home-greeting-name');
        if (greetName) greetName.textContent = auth.name || 'Relief Partner';
    }
}

// Switch between Sign In and Register tabs
function setAuthMode(mode) {
    const tabSignin = document.getElementById('auth-mode-signin');
    const tabRegister = document.getElementById('auth-mode-register');
    const formSignin = document.getElementById('signin-form');
    const formRegister = document.getElementById('register-form');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const alertBox = document.getElementById('auth-alert-box');
    const authSwitchPrompt = document.getElementById('authSwitchPrompt');
    
    if (alertBox) alertBox.classList.add('hidden');

    if (mode === 'signin') {
        if (tabSignin) {
            tabSignin.classList.add('active');
            tabSignin.style.borderBottom = '2px solid var(--primary)';
            tabSignin.style.color = 'var(--primary)';
            tabSignin.style.fontWeight = '700';
        }
        if (tabRegister) {
            tabRegister.classList.remove('active');
            tabRegister.style.borderBottom = 'none';
            tabRegister.style.color = 'var(--text-muted)';
            tabRegister.style.fontWeight = '600';
        }
        if (formSignin) formSignin.classList.remove('hidden');
        if (formRegister) formRegister.classList.add('hidden');
        if (authTitle) authTitle.textContent = 'Welcome Back!';
        if (authSubtitle) authSubtitle.textContent = 'Login to continue your Serviqo AI journey';
        if (authSwitchPrompt) {
            authSwitchPrompt.innerHTML = `Don't have an account? <button class="text-btn signup-btn" id="signupBtn" type="button" onclick="setAuthMode('register')">Sign Up</button>`;
        }
    } else {
        if (tabRegister) {
            tabRegister.classList.add('active');
            tabRegister.style.borderBottom = '2px solid var(--primary)';
            tabRegister.style.color = 'var(--primary)';
            tabRegister.style.fontWeight = '700';
        }
        if (tabSignin) {
            tabSignin.classList.remove('active');
            tabSignin.style.borderBottom = 'none';
            tabSignin.style.color = 'var(--text-muted)';
            tabSignin.style.fontWeight = '600';
        }
        if (formSignin) formSignin.classList.add('hidden');
        if (formRegister) formRegister.classList.remove('hidden');
        if (authTitle) authTitle.textContent = 'Create an Account';
        if (authSubtitle) authSubtitle.textContent = 'Register as Srinivas Canteen staff or a verified relief partner.';
        if (authSwitchPrompt) {
            authSwitchPrompt.innerHTML = `Already have an account? <button class="text-btn signup-btn" id="signinBtn" type="button" onclick="setAuthMode('signin')">Sign In</button>`;
        }
    }
}

function showAuthAlert(message, type = 'danger') {
    const alertBox = document.getElementById('auth-alert-box');
    if (!alertBox) {
        showToast(message, type);
        return;
    }
    alertBox.textContent = message;
    alertBox.classList.remove('hidden');

    if (type === 'danger') {
        alertBox.style.background = 'rgba(239, 68, 68, 0.12)';
        alertBox.style.color = '#ef4444';
        alertBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
    } else if (type === 'success') {
        alertBox.style.background = 'rgba(16, 185, 129, 0.12)';
        alertBox.style.color = '#10b981';
        alertBox.style.border = '1px solid rgba(16, 185, 129, 0.3)';
    } else {
        alertBox.style.background = 'rgba(59, 130, 246, 0.12)';
        alertBox.style.color = '#3b82f6';
        alertBox.style.border = '1px solid rgba(59, 130, 246, 0.3)';
    }
}

function togglePasswordVisibility(inputId, btnEl) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';
    if (btnEl) {
        btnEl.innerHTML = isPassword ? `<i class="ph ph-eye-slash"></i>` : `<i class="ph ph-eye"></i>`;
    }
}

function onRegisterRoleChange() {
    const roleSelect = document.getElementById('reg-role');
    const orgInput = document.getElementById('reg-org');
    const orgLabel = document.getElementById('reg-org-label');
    const ngoDetails = document.getElementById('reg-ngo-details');
    if (!roleSelect || !orgInput) return;

    if (roleSelect.value === 'Kitchen Staff') {
        if (orgLabel) orgLabel.textContent = 'Organization Name';
        orgInput.value = 'Srinivas Institute Canteen';
        orgInput.placeholder = 'Srinivas Institute Canteen';
        if (ngoDetails) ngoDetails.classList.add('hidden');
    } else {
        if (orgLabel) orgLabel.textContent = 'NGO / Relief Partner Organization Name';
        orgInput.value = '';
        orgInput.placeholder = 'e.g. Hope Relief Foundation';
        if (ngoDetails) ngoDetails.classList.remove('hidden');
    }
}

// Pure Database-Backed Sign In
async function handleLoginSubmit(event) {
    if (event) event.preventDefault();
    const emailInput = document.getElementById('auth-email');
    const passwordInput = document.getElementById('auth-password');
    const submitBtn = document.getElementById('auth-signin-btn');
    const alertBox = document.getElementById('auth-alert-box');

    const email = emailInput ? emailInput.value.trim() : '';
    const password = passwordInput ? passwordInput.value : '';

    if (!email || !password) {
        showAuthAlert('Please enter both your registered email address and password.', 'danger');
        return;
    }

    if (alertBox) alertBox.classList.add('hidden');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="ph ph-spinner ph-spin"></i> Verifying Credentials...`;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            const message = response.status === 401 
                ? 'Incorrect email or password.' 
                : (data.detail || 'Authentication failed. Please verify your credentials.');
            showAuthAlert(message, 'danger');
            return;
        }

        // Authentication Success: Store database user record in session
        const user = data.user;
        setAuth(user);

        showToast(`Welcome back, ${user.name}! Authenticated as ${user.role}.`, 'success');

        // Route to the role's primary workspace strictly based on database role
        if (isCanteenRole(user.role)) {
            navigateTo('canteen-home');
        } else {
            navigateTo('ngo-home');
        }

    } catch (err) {
        console.error('Login error:', err);
        showAuthAlert('Unable to connect to the server. Please try again.', 'danger');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `Sign In to Portal →`;
        }
    }
}

// Pure Database-Backed Registration
async function handleRegisterSubmit(event) {
    if (event) event.preventDefault();
    const nameInput = document.getElementById('reg-name');
    const emailInput = document.getElementById('reg-email');
    const passwordInput = document.getElementById('reg-password');
    const confirmPasswordInput = document.getElementById('reg-confirm-password');
    const roleSelect = document.getElementById('reg-role');
    const orgInput = document.getElementById('reg-org');
    const submitBtn = document.getElementById('auth-register-btn');

    const name = nameInput ? nameInput.value.trim() : '';
    const email = emailInput ? emailInput.value.trim() : '';
    const password = passwordInput ? passwordInput.value : '';
    const confirmPassword = confirmPasswordInput ? confirmPasswordInput.value : '';
    const role = roleSelect ? roleSelect.value : '';
    const org = orgInput ? orgInput.value.trim() : '';

    // Frontend Validations
    if (!name || name.length < 2) {
        showAuthAlert('Please enter your full name.', 'danger');
        if (nameInput) nameInput.focus();
        return;
    }

    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email || !emailPattern.test(email)) {
        showAuthAlert('Please enter a valid email address.', 'danger');
        if (emailInput) emailInput.focus();
        return;
    }

    if (!password || password.length < 4) {
        showAuthAlert('Password must be at least 4 characters long.', 'danger');
        if (passwordInput) passwordInput.focus();
        return;
    }

    if (password !== confirmPassword) {
        showAuthAlert('Passwords do not match.', 'danger');
        if (confirmPasswordInput) confirmPasswordInput.focus();
        return;
    }

    if (!role) {
        showAuthAlert('Please select your organization type.', 'danger');
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="ph ph-spinner ph-spin"></i> Creating Account...`;
    }

    try {
        const organization = org || (isCanteenRole(role) ? 'Srinivas Institute Canteen' : 'Registered NGO Partner');

        const payload = {
            name,
            email,
            password,
            role,
            organization
        };

        if (isNgoRole(role)) {
            const phoneInput = document.getElementById('reg-phone');
            const addressInput = document.getElementById('reg-address');
            const capacityInput = document.getElementById('reg-capacity');
            const needInput = document.getElementById('reg-need-level');

            payload.phone = phoneInput ? phoneInput.value.trim() : null;
            payload.address = addressInput ? addressInput.value.trim() : null;
            payload.capacity_persons = capacityInput ? (parseInt(capacityInput.value, 10) || 150) : 150;
            payload.need_level = needInput ? needInput.value : 'medium';
        }

        const response = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            const isDuplicate = response.status === 400 || (data.detail && data.detail.toLowerCase().includes('already registered'));
            const errorMsg = isDuplicate 
                ? 'An account with this email already exists.' 
                : (data.detail || 'Registration failed. Please check your information.');
            showAuthAlert(errorMsg, 'danger');
            return;
        }

        // Registration Success: Return user to Sign In with email prefilled
        showToast('Registration successful! Please sign in with your credentials.', 'success');
        setAuthMode('signin');

        const loginEmail = document.getElementById('auth-email');
        const loginPass = document.getElementById('auth-password');
        if (loginEmail) loginEmail.value = email;
        if (loginPass) {
            loginPass.value = '';
            loginPass.focus();
        }

        // Reset registration fields
        if (nameInput) nameInput.value = '';
        if (emailInput) emailInput.value = '';
        if (passwordInput) passwordInput.value = '';
        if (confirmPasswordInput) confirmPasswordInput.value = '';

        showAuthAlert('Account created successfully! Please sign in with your password.', 'success');

    } catch (err) {
        console.error('Registration error:', err);
        showAuthAlert('Unable to connect to the server. Please try again.', 'danger');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `Create Account →`;
        }
    }
}

// Profile Dropdown & Modal Logic
function toggleProfileDropdown(event) {
    if (event) event.stopPropagation();
    const auth = getAuth();
    if (!auth) {
        navigateTo('login');
        return;
    }
    const menu = document.getElementById('profile-dropdown-menu');
    if (menu) menu.classList.toggle('hidden');
}

function openEditProfileModal() {
    const menu = document.getElementById('profile-dropdown-menu');
    if (menu) menu.classList.add('hidden');

    const auth = getAuth();
    if (!auth) {
        navigateTo('login');
        return;
    }

    const editName = document.getElementById('edit-profile-name');
    const editEmail = document.getElementById('edit-profile-email');
    const editRole = document.getElementById('edit-profile-role');
    const editOrg = document.getElementById('edit-profile-org');
    const alertBox = document.getElementById('edit-profile-alert');

    if (editName) editName.value = auth.name || '';
    if (editEmail) editEmail.value = auth.email || '';
    if (editRole) editRole.value = auth.role || '';
    if (editOrg) editOrg.value = auth.organization || '';
    if (alertBox) alertBox.classList.add('hidden');

    const modal = document.getElementById('edit-profile-modal');
    if (modal) modal.classList.add('active');
}

function closeEditProfileModal() {
    const modal = document.getElementById('edit-profile-modal');
    if (modal) modal.classList.remove('active');
}

function showProfileAlert(message, type = 'danger') {
    const alertBox = document.getElementById('edit-profile-alert');
    if (!alertBox) return;
    alertBox.textContent = message;
    alertBox.classList.remove('hidden');

    if (type === 'danger') {
        alertBox.style.background = 'rgba(239, 68, 68, 0.12)';
        alertBox.style.color = '#ef4444';
        alertBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
    } else {
        alertBox.style.background = 'rgba(16, 185, 129, 0.12)';
        alertBox.style.color = '#10b981';
        alertBox.style.border = '1px solid rgba(16, 185, 129, 0.3)';
    }
}

async function handleProfileUpdate(event) {
    if (event) event.preventDefault();
    const auth = getAuth();
    if (!auth) {
        closeEditProfileModal();
        navigateTo('login');
        return;
    }

    const editName = document.getElementById('edit-profile-name');
    const newName = editName ? editName.value.trim() : '';
    const saveBtn = document.getElementById('edit-profile-save-btn');

    if (!newName || newName.length < 2) {
        showProfileAlert('Please enter your full name.', 'danger');
        return;
    }

    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<i class="ph ph-spinner ph-spin"></i> Saving...`;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/profile`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: auth.id,
                name: newName
            })
        });

        const data = await response.json();

        if (!response.ok) {
            showProfileAlert(data.detail || 'Unable to update profile name in database.', 'danger');
            return;
        }

        // Update session auth with updated user record
        const updatedUser = data.user;
        auth.name = updatedUser.name;
        setAuth(auth);

        closeEditProfileModal();
        showToast('Profile name updated successfully in MySQL!', 'success');

    } catch (err) {
        console.error('Profile update error:', err);
        showProfileAlert('Server error updating profile.', 'danger');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = `Save Changes`;
        }
    }
}

function handleLogout() {
    const menu = document.getElementById('profile-dropdown-menu');
    if (menu) menu.classList.add('hidden');
    const notifMenu = document.getElementById('notifications-dropdown-menu');
    if (notifMenu) notifMenu.classList.add('hidden');
    if (typeof notifPollInterval !== 'undefined' && notifPollInterval) {
        clearInterval(notifPollInterval);
        notifPollInterval = null;
    }
    setAuth(null);
    showToast('Signed out successfully. Authentication session ended.', 'info');
    const shell = document.getElementById('landingShell');
    if (shell) shell.classList.remove('show-login');
    navigateTo('login');
}


// =========================================================================
// 2. SPA NAVIGATION & ROLE-BASED ACCESS CONTROL (RBAC)
// =========================================================================

const pageTitles = {
    'login': { title: 'Authentication', subtitle: 'Sign in to access your role-specific operational workspace' },
    // Canteen Workspace
    'canteen-home': { title: 'Operational Home', subtitle: 'Today\'s kitchen overview, attendance, predicted demand & stock alerts' },
    'canteen-demand': { title: 'Demand Intelligence', subtitle: 'LightGBM Machine Learning prediction & batch planning' },
    'canteen-inventory': { title: 'Food Inventory', subtitle: 'Live stock monitoring, shelf life tracking & reorder warnings' },
    'canteen-recovery': { title: 'Food Redistribution', subtitle: 'Publish surplus batches to all partner organizations & coordinate inventory reservations' },
    'canteen-ngos': { title: 'Registered NGO Partners', subtitle: 'Verified relief partners and emergency shelter directory in Mangalore' },
    'canteen-analytics': { title: 'Kitchen Analytics', subtitle: 'Preparation efficiency, overproduction avoidance & food saved audit' },
    'canteen-announcements': { title: 'Staff Announcements', subtitle: 'Internal communications and operational kitchen directives' },
    'canteen-profile': { title: 'Canteen Settings', subtitle: 'Operational credentials and MySQL database architecture' },
    // NGO Workspace
    'ngo-home': { title: 'Relief Command Center', subtitle: 'Incoming surplus food offers, action items and verified impact' },
    'ngo-incoming': { title: 'Available Surplus Food Feed', subtitle: 'Browse live surplus batches from Srinivas Canteen and request needed quantities' },
    'ngo-requests': { title: 'My Food Requests', subtitle: 'Track your organization\'s requests, held reservations and supplier decisions' },
    'ngo-schedule': { title: 'Pickup Schedule', subtitle: 'Upcoming surplus collections scheduled at Srinivas Canteen' },
    'ngo-received': { title: 'Received Food History', subtitle: 'Audit log of completed donations and distribution confirmations' },
    'ngo-canteens': { title: 'Connected Canteens', subtitle: 'Verified food donors and campus kitchen partners' },
    'ngo-history': { title: 'Recovery Audit Trail', subtitle: 'Chronological timeline of all donation requests and status transitions' },
    'ngo-analytics': { title: 'Relief Impact Analytics', subtitle: 'Donation acceptance rate, food intake volume & meals provided' },
    'ngo-announcements': { title: 'Community Notices', subtitle: 'Operational directives from kitchen partners and coordinators' },
    'ngo-profile': { title: 'Relief Partner Profile', subtitle: 'Organization credentials, shelter capacity and need level' }
};

function navigateTo(targetId) {
    const auth = getAuth();

    // Alias mapping for backward compatibility
    const aliases = {
        'home': auth && isNgoRole(auth.role) ? 'ngo-home' : 'canteen-home',
        'dashboard': 'canteen-home',
        'inventory': 'canteen-inventory',
        'kitchen-demand': 'canteen-demand',
        'redistribution': 'canteen-recovery',
        'recovery': 'canteen-recovery',
        'available-food': 'ngo-incoming',
        'my-requests': 'ngo-requests',
        'schedule': 'ngo-schedule',
        'suppliers': auth && isNgoRole(auth.role) ? 'ngo-canteens' : 'canteen-ngos',
        'analytics': auth && isNgoRole(auth.role) ? 'ngo-analytics' : 'canteen-analytics',
        'announcements': auth && isNgoRole(auth.role) ? 'ngo-announcements' : 'canteen-announcements'
    };

    if (aliases[targetId]) {
        targetId = aliases[targetId];
    }

    // Role-based Access Control Guard
    if (targetId !== 'login') {
        if (!auth) {
            targetId = 'login';
        } else if (isCanteenRole(auth.role) && targetId.startsWith('ngo-')) {
            showToast('Access denied: NGO workspace is restricted to registered relief partners.', 'danger');
            targetId = 'canteen-home';
        } else if (isNgoRole(auth.role) && targetId.startsWith('canteen-')) {
            showToast('Access denied: Kitchen operations are restricted to canteen staff.', 'danger');
            targetId = 'ngo-home';
        }
    }

    // Switch visible sections
    const sections = document.querySelectorAll('.page-section');
    sections.forEach(sec => {
        sec.classList.add('hidden');
        sec.classList.remove('active');
    });

    const targetSec = document.getElementById(targetId);
    if (targetSec) {
        targetSec.classList.remove('hidden');
        targetSec.classList.add('active');
    }

    // Update active state on sidebar buttons
    const sidebarBtns = document.querySelectorAll('.sidebar-btn');
    sidebarBtns.forEach(btn => {
        if (btn.getAttribute('data-target') === targetId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update header text
    if (pageTitles[targetId]) {
        const titleEl = document.getElementById('header-page-title');
        const subEl = document.getElementById('header-page-subtitle');
        if (titleEl) titleEl.textContent = pageTitles[targetId].title;
        if (subEl) subEl.textContent = pageTitles[targetId].subtitle;
    }

    // Close mobile menu if open
    const sidebar = document.querySelector('.sidebar');
    if (sidebar && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Section-specific Data Initializers
    if (targetId === 'canteen-home') {
        loadCanteenHomeData();
    } else if (targetId === 'canteen-demand') {
        checkMlStatus();
        initSupplierDemandChart();
    } else if (targetId === 'canteen-inventory') {
        loadFullInventoryPage();
    } else if (targetId === 'canteen-recovery') {
        loadCanteenRecoveryTable();
    } else if (targetId === 'canteen-ngos') {
        loadCanteenNgos();
        setTimeout(() => {
            if (canteenNgoMap) canteenNgoMap.invalidateSize();
        }, 250);
    } else if (targetId === 'canteen-analytics') {
        loadCanteenAnalytics();
    } else if (targetId === 'canteen-announcements') {
        loadCanteenAnnouncements();
    } else if (targetId === 'ngo-home') {
        loadNgoHomeData();
    } else if (targetId === 'ngo-incoming') {
        loadNgoIncomingPage();
    } else if (targetId === 'ngo-requests') {
        loadNgoRequestsPage();
    } else if (targetId === 'ngo-schedule') {
        loadNgoSchedulePage();
    } else if (targetId === 'ngo-received') {
        loadNgoReceivedPage();
    } else if (targetId === 'ngo-canteens') {
        loadNgoCanteensPage();
    } else if (targetId === 'ngo-history') {
        loadNgoHistoryPage();
    } else if (targetId === 'ngo-analytics') {
        loadNgoAnalyticsPage();
    } else if (targetId === 'ngo-announcements') {
        loadNgoAnnouncementsPage();
    }
}


// =========================================================================
// 3. CANTEEN / KITCHEN WORKSPACE LOGIC
// =========================================================================

// --- 3.1 Canteen Operational Home ---
async function loadCanteenHomeData() {
    const auth = getAuth();
    const greetingEl = document.getElementById('canteen-home-greeting-name');
    if (greetingEl && auth) greetingEl.textContent = auth.name || 'Kitchen Staff';

    const dateEl = document.getElementById('canteen-home-date');
    if (dateEl) {
        dateEl.textContent = new Date().toLocaleDateString('en-US', {
            weekday: 'long',
            month: 'short',
            day: 'numeric'
        });
    }

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/canteen`);
        if (!res.ok) throw new Error('Failed to load canteen dashboard');
        const data = await res.json();
        const kpi = data.kpis;
        cachedCanteenKpis = kpi;

        // Top 6 Real KPI Cards
        const elDemand = document.getElementById('canteen-kpi-demand');
        const elAttendance = document.getElementById('canteen-kpi-attendance');
        const elRisk = document.getElementById('canteen-kpi-risk');
        const elSurplus = document.getElementById('canteen-kpi-surplus');
        const elRequests = document.getElementById('canteen-kpi-requests');
        const elRecovered = document.getElementById('canteen-kpi-recovered');

        const surplusCount = kpi.surplus?.count ?? kpi.surplus?.surplus_items ?? kpi.inventory?.surplus_items ?? kpi.surplus_food_items ?? 0;
        const activeRequestsCount = kpi.donations?.active_requests ?? kpi.donations?.active_recovery_requests ?? kpi.active_recovery_requests ?? 0;

        if (elDemand) elDemand.textContent = `${kpi.demand?.predicted_demand ?? kpi.predicted_demand ?? 0} Servings`;
        if (elAttendance) elAttendance.textContent = `${kpi.demand?.attendance ?? kpi.attendance ?? 0} Students`;
        if (elRisk) elRisk.textContent = `${kpi.inventory?.inventory_at_risk ?? kpi.inventory_at_risk ?? 0} Items`;
        if (elSurplus) elSurplus.textContent = `${surplusCount} Batches`;
        if (elRequests) elRequests.textContent = `${activeRequestsCount} Active`;
        if (elRecovered) elRecovered.textContent = `${(kpi.donations?.food_saved_kg ?? kpi.food_saved_kg ?? 0).toLocaleString()} kg`;

        // Operational Demand Summary
        const elMeal = document.getElementById('canteen-home-meal-slot');
        const elPrep = document.getElementById('canteen-home-prep-qty');
        const elWeather = document.getElementById('canteen-home-weather');
        const elEff = document.getElementById('canteen-home-efficiency');

        if (elMeal) elMeal.textContent = (kpi.demand.meal_type || 'Lunch').toUpperCase();
        if (elPrep) elPrep.textContent = `${kpi.demand.recommended_prep || 0} Servings`;
        if (elWeather) elWeather.textContent = kpi.demand.weather || 'Clear / Sunny';
        if (elEff) elEff.textContent = `${kpi.operations.prep_efficiency_pct || 94}%`;

        // Operational Alerts
        renderCanteenAlerts(kpi);

    } catch (err) {
        console.warn('Error loading canteen home data:', err);
    }
}

function renderCanteenAlerts(kpi) {
    const container = document.getElementById('canteen-home-alerts-container');
    if (!container) return;

    const alerts = [];

    if (kpi.inventory?.near_expiry_items > 0) {
        alerts.push({
            type: 'warning',
            icon: 'ph-warning',
            title: `${kpi.inventory.near_expiry_items} Stock Batches Near Expiry (≤ 2 Days)`,
            desc: 'Consider allocating to immediate meal preparation or dispatching to partner NGOs for food recovery.'
        });
    }

    const surplusCount = kpi.surplus?.count ?? kpi.surplus?.surplus_items ?? kpi.inventory?.surplus_items ?? kpi.surplus_food_items ?? 0;
    if (surplusCount > 0) {
        alerts.push({
            type: 'success',
            icon: 'ph-recycle',
            title: `${surplusCount} Surplus Batches Ready for Recovery`,
            desc: 'Surplus food detected in kitchen stock. Connected relief partners are ready to receive dispatches.'
        });
    }

    if (kpi.donations?.pending > 0) {
        alerts.push({
            type: 'info',
            icon: 'ph-paper-plane-tilt',
            title: `${kpi.donations.pending} Recovery Request(s) Awaiting NGO Pickup`,
            desc: 'Recovery offers dispatched to registered NGO partners. Track confirmation in the Food Recovery tab.'
        });
    }

    if (alerts.length === 0) {
        container.innerHTML = `
            <div style="background: var(--bg-body); border-left: 4px solid var(--success); padding: 1rem; border-radius: var(--radius-sm); display: flex; align-items: center; gap: 0.75rem;">
                <i class="ph ph-check-circle" style="font-size: 1.5rem; color: var(--success);"></i>
                <div>
                    <h4 style="font-size: 0.92rem; font-weight: 700; margin: 0; color: var(--text-primary);">All Operations Smooth</h4>
                    <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 2px 0 0 0;">Inventory fresh, demand forecasts synced, and no critical risk alerts right now.</p>
                </div>
            </div>
        `;
        return;
    }

    container.innerHTML = alerts.map(a => `
        <div style="background: var(--bg-body); border-left: 4px solid var(--${a.type}); padding: 0.85rem 1rem; border-radius: var(--radius-sm); display: flex; align-items: flex-start; gap: 0.75rem;">
            <i class="ph ${a.icon}" style="font-size: 1.35rem; color: var(--${a.type}); margin-top: 2px;"></i>
            <div>
                <h4 style="font-size: 0.88rem; font-weight: 700; margin: 0; color: var(--text-primary);">${a.title}</h4>
                <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 2px 0 0 0;">${a.desc}</p>
            </div>
        </div>
    `).join('');
}

// --- 3.2 Demand Intelligence & ML Forecasting ---
async function checkMlStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml-status`);
        if (res.ok) {
            const data = await res.json();
            const text = document.getElementById('ml-status-text');
            const badge = document.getElementById('ml-engine-badge');
            if (text && badge) {
                if (data.model_file_exists) {
                    text.textContent = `LightGBM Active (${data.model_engine})`;
                    badge.className = 'badge badge-success';
                } else {
                    text.textContent = 'ML Fallback Engine Active';
                    badge.className = 'badge badge-warning';
                }
            }
        }
    } catch (e) {}
}

function switchMealTab(meal) {
    currentMealTab = meal;
    document.querySelectorAll('.meal-select-btn').forEach(btn => {
        if (btn.getAttribute('data-meal') === meal) {
            btn.className = 'btn-primary meal-select-btn';
        } else {
            btn.className = 'btn-secondary meal-select-btn';
        }
    });
}

const demandForecastForm = document.getElementById('demand-forecast-form');
if (demandForecastForm) {
    demandForecastForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const attendance = parseInt(document.getElementById('demand-attendance')?.value) || 150;
        const hostelAttendance = parseInt(document.getElementById('demand-hostel-attendance')?.value) || 0;
        const dayScholarAttendance = parseInt(document.getElementById('demand-dayscholar-attendance')?.value) || 0;
        const temperature = parseFloat(document.getElementById('demand-temperature')?.value) || 28.0;
        const rainfall = parseFloat(document.getElementById('demand-rainfall')?.value) || 0.0;
        const humidity = parseFloat(document.getElementById('demand-humidity')?.value) || 65.0;
        const dayType = document.getElementById('demand-daytype')?.value || 'weekday';
        const isExam = document.getElementById('demand-examday')?.value === 'true';
        const isEvent = document.getElementById('demand-event')?.value === 'true';
        const popularity = parseInt(document.getElementById('demand-popularity')?.value) || 2;

        const payload = {
            meal_type: currentMealTab,
            attendance,
            hostel_attendance: hostelAttendance,
            dayscholar_attendance: dayScholarAttendance,
            temperature_c: temperature,
            rainfall_mm: rainfall,
            humidity_pct: humidity,
            is_weekend: dayType === 'weekend',
            is_holiday: dayType === 'holiday',
            is_exam_day: isExam,
            is_campus_event: isEvent,
            popularity_level: popularity
        };

        const submitBtn = demandForecastForm.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<i class="ph ph-spinner ph-spin"></i> Running LightGBM Model...`;
        }

        try {
            const res = await fetch(`${API_BASE}/api/demand-forecast`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) throw new Error('Prediction API failed');
            const data = await res.json();

            // Display Results
            const initState = document.getElementById('forecast-initial-state');
            const resState = document.getElementById('forecast-result-state');
            if (initState) initState.classList.add('hidden');
            if (resState) resState.classList.remove('hidden');

            const totalEl = document.getElementById('forecast-total-demand');
            const prepEl = document.getElementById('forecast-prep-text');
            const bufferEl = document.getElementById('forecast-buffer-text');
            const recEl = document.getElementById('demand-rec-text');
            const modelBadge = document.getElementById('forecast-model-badge');

            if (totalEl) totalEl.textContent = `${data.predicted_demand} Servings`;
            if (prepEl) prepEl.textContent = `${data.recommended_prep} Servings`;
            if (bufferEl) bufferEl.textContent = `Includes +${data.safety_buffer_percent || 0}% safety prep buffer (${data.safety_buffer || 0} servings)`;
            if (recEl) recEl.textContent = data.recommendation;
            if (modelBadge) modelBadge.textContent = data.model_engine || 'LightGBM Production Engine';

            // Portion Breakdown: clearly displays predicted demand vs recommended safe prep
            const breakdownContainer = document.getElementById('menu-demand-items');
            if (breakdownContainer && data.top_items) {
                breakdownContainer.innerHTML = data.top_items.map(item => {
                    const riskBadge = item.waste_risk === 'high' ? 'badge-danger' : (item.waste_risk === 'medium' ? 'badge-warning' : 'badge-success');
                    return `
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.65rem 0; border-bottom: 1px solid var(--border-subtle);">
                            <div>
                                <strong style="color: var(--text-primary); font-size: 0.9rem;">${item.name}</strong>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">
                                    Risk: <span class="badge ${riskBadge}">${item.waste_risk.toUpperCase()}</span>
                                    <span style="margin-left: 6px; color: var(--text-secondary);">Prep: <strong style="color: var(--success-text);">${item.safe_prep}</strong> ${item.unit}</span>
                                </div>
                            </div>
                            <div style="text-align: right;">
                                <strong style="font-size: 1.15rem; color: var(--primary);">${item.quantity}</strong>
                                <span style="font-size: 0.8rem; color: var(--text-secondary); margin-left: 2px;">${item.unit} (demand)</span>
                            </div>
                        </div>
                    `;
                }).join('');
            }


            showToast(`LightGBM Prediction completed & persisted to MySQL for ${currentMealTab.toUpperCase()}!`, 'success');

            // Refresh historical chart
            initSupplierDemandChart();

        } catch (err) {
            console.error('Forecast error:', err);
            showToast('Failed to generate demand prediction. Check backend logs.', 'danger');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<i class="ph ph-sparkle"></i> Generate ML Demand Prediction`;
            }
        }
    });
}

async function initSupplierDemandChart() {
    const ctx = document.getElementById('supplierDemandChart');
    if (!ctx) return;

    let labels = [];
    let demandData = [];
    let prepData = [];

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/demand-trend?limit=7`);
        if (res.ok) {
            const data = await res.json();
            labels = data.labels || [];
            demandData = data.demand || [];
            prepData = data.recommended_prep || [];
        }
    } catch (e) {
        console.warn('Error loading demand trend:', e);
    }

    if (labels.length === 0) {
        labels = ['No Historical Data'];
        demandData = [0];
        prepData = [0];
    }

    if (supplierDemandChartInstance) {
        supplierDemandChartInstance.destroy();
    }

    supplierDemandChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Predicted Demand (Servings)',
                    data: demandData,
                    backgroundColor: 'rgba(44, 168, 91, 0.85)',
                    borderRadius: 6
                },
                {
                    label: 'Recommended Prep (Servings)',
                    data: prepData,
                    backgroundColor: 'rgba(101, 200, 133, 0.85)',
                    borderRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', font: { family: 'Inter', size: 12, weight: 600 } } }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { family: 'Inter' } } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.08)' }, ticks: { color: '#94a3b8', font: { family: 'Inter' } }, beginAtZero: true }
            }
        }
    });
}

// --- 3.3 Inventory Management (Real MySQL CRUD) ---
async function loadFullInventoryPage() {
    const tbody = document.getElementById('full-inventory-body');
    if (!tbody) return;

    try {
        const res = await fetch(`${API_BASE}/api/inventory`);
        if (!res.ok) throw new Error('Inventory fetch failed');
        cachedInventory = await res.json();

        // Calculate and update genuine summary counters
        updateInventorySummaryCounters(cachedInventory);

        renderFilteredFullInventory();
    } catch (err) {
        console.error('Error fetching inventory:', err);
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">Failed to load inventory from MySQL.</td></tr>`;
    }
}

function updateInventorySummaryCounters(items) {
    const totalEl = document.getElementById('inv-summary-total');
    const availEl = document.getElementById('inv-summary-avail-qty');
    const nearEl = document.getElementById('inv-summary-near-expiry');
    const lowEl = document.getElementById('inv-summary-low-stock');

    const totalCount = items.length;
    let availQty = 0;
    let nearExpiry = 0;
    let lowStock = 0;

    items.forEach(item => {
        if ((item.status || '').toLowerCase() !== 'donated') {
            availQty += parseFloat(item.quantity) || 0;
        }
        if (parseInt(item.expiry_days) <= 2) {
            nearExpiry++;
        }
        if (parseFloat(item.quantity) < 5 || (item.status || '').toUpperCase() === 'LOW STOCK') {
            lowStock++;
        }
    });

    if (totalEl) totalEl.textContent = totalCount;
    if (availEl) availEl.textContent = `${availQty.toFixed(1)} kg/units`;
    if (nearEl) nearEl.textContent = `${nearExpiry} Items`;
    if (lowEl) lowEl.textContent = `${lowStock} Items`;
}

function renderFilteredFullInventory() {
    const tbody = document.getElementById('full-inventory-body');
    if (!tbody) return;

    const searchTerm = document.getElementById('inventory-search')?.value.toLowerCase() || '';
    const categoryFilter = document.getElementById('inventory-filter')?.value || 'all';

    const filtered = cachedInventory.filter(item => {
        const itemName = (item.name || item.item_name || '').toLowerCase();
        const cat = (item.category || '').toLowerCase();
        const matchesCategory = categoryFilter === 'all' || cat === categoryFilter.toLowerCase();
        const matchesSearch = itemName.includes(searchTerm) || cat.includes(searchTerm);
        return matchesCategory && matchesSearch;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No inventory items match search criteria.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(item => {
        const days = parseInt(item.expiry_days);
        const qty = parseFloat(item.quantity);
        let statusBadge = `<span class="badge badge-success">Fresh</span>`;
        if (days <= 1) statusBadge = `<span class="badge badge-danger">Critical Expiry (≤1d)</span>`;
        else if (days <= 2) statusBadge = `<span class="badge badge-warning">Near Expiry (2d)</span>`;
        else if (qty < 5) statusBadge = `<span class="badge badge-purple">Low Stock</span>`;

        if ((item.status || '').toUpperCase() === 'DONATED') {
            statusBadge = `<span class="badge badge-info">Recovered / Donated</span>`;
        } else if ((item.status || '').toUpperCase() === 'SURPLUS') {
            statusBadge = `<span class="badge badge-success">Marked Surplus</span>`;
        }

        const isDonated = (item.status || '').toLowerCase() === 'donated';

        return `
            <tr>
                <td><strong>${item.name || item.item_name}</strong></td>
                <td><span class="status-pill safe">${item.category || 'Kitchen'}</span></td>
                <td><strong>${item.quantity}</strong></td>
                <td>${item.unit || 'kg'}</td>
                <td>${item.expiry_days} Days</td>
                <td>${statusBadge}</td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">${item.suggested_action || 'Safe for service'}</td>
                <td>
                    <div style="display: flex; gap: 6px; align-items: center;">
                        <button class="btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="openEditInventoryModal(${item.id})" title="Edit Item">
                            <i class="ph ph-pencil-simple"></i>
                        </button>
                        ${!isDonated ? `
                            <button class="btn-primary" style="padding: 4px 8px; font-size: 0.75rem; background: var(--success); border-color: var(--success);" onclick="openSurplusDonationModalWithItem(${item.id})" title="Dispatch as Recovery">
                                <i class="ph ph-heart"></i>
                            </button>
                        ` : ''}
                        <button class="btn-secondary" style="padding: 4px 8px; font-size: 0.75rem; color: var(--danger); border-color: rgba(239, 68, 68, 0.3);" onclick="deleteInventoryItem(${item.id})" title="Delete Item">
                            <i class="ph ph-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

// Add Inventory Modal
function openAddInventoryModal() {
    const modal = document.getElementById('add-inventory-modal');
    if (modal) modal.classList.add('active');
}
function closeAddInventoryModal() {
    const modal = document.getElementById('add-inventory-modal');
    if (modal) modal.classList.remove('active');
}

async function submitNewInventory(event) {
    if (event) event.preventDefault();
    const name = document.getElementById('inv-new-name')?.value.trim();
    const category = document.getElementById('inv-new-category')?.value;
    const quantity = parseFloat(document.getElementById('inv-new-quantity')?.value);
    const unit = document.getElementById('inv-new-unit')?.value;
    const expiry_days = parseInt(document.getElementById('inv-new-expiry-days')?.value);

    if (!name || isNaN(quantity) || isNaN(expiry_days)) {
        showToast('Please provide valid food item details.', 'danger');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/inventory`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                category,
                quantity,
                unit,
                expiry_days,
                supplier_name: 'Srinivas Institute Canteen'
            })
        });

        if (!res.ok) throw new Error('API creation failed');

        showToast(`Added ${name} (${quantity} ${unit}) to MySQL inventory!`, 'success');
        closeAddInventoryModal();
        document.getElementById('add-inventory-form')?.reset();
        loadFullInventoryPage();
        loadCanteenHomeData();

    } catch (err) {
        console.error('Error saving inventory:', err);
        showToast('Failed to save item to MySQL database.', 'danger');
    }
}

// Edit Inventory Modal
function openEditInventoryModal(itemId) {
    const item = cachedInventory.find(i => i.id === itemId);
    if (!item) return;

    document.getElementById('edit-inv-id').value = item.id;
    document.getElementById('edit-inv-name').value = item.name || item.item_name;
    document.getElementById('edit-inv-quantity').value = item.quantity;
    document.getElementById('edit-inv-expiry-days').value = item.expiry_days;
    document.getElementById('edit-inv-status').value = item.status || 'AVAILABLE';

    const modal = document.getElementById('edit-inventory-modal');
    if (modal) modal.classList.add('active');
}
function closeEditInventoryModal() {
    const modal = document.getElementById('edit-inventory-modal');
    if (modal) modal.classList.remove('active');
}

async function submitEditInventory(event) {
    if (event) event.preventDefault();
    const id = document.getElementById('edit-inv-id')?.value;
    const quantity = parseFloat(document.getElementById('edit-inv-quantity')?.value);
    const expiry_days = parseInt(document.getElementById('edit-inv-expiry-days')?.value);
    const status = document.getElementById('edit-inv-status')?.value;

    try {
        const res = await fetch(`${API_BASE}/api/inventory/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quantity, expiry_days, status })
        });

        if (!res.ok) throw new Error('Update failed');

        showToast('Inventory item updated successfully in MySQL!', 'success');
        closeEditInventoryModal();
        loadFullInventoryPage();
        loadCanteenHomeData();

    } catch (err) {
        console.error('Error updating inventory:', err);
        showToast('Failed to update inventory item.', 'danger');
    }
}

async function deleteInventoryItem(itemId) {
    if (!confirm('Are you sure you want to permanently remove this food item from MySQL inventory?')) return;

    try {
        const res = await fetch(`${API_BASE}/api/inventory/${itemId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');

        showToast('Item removed from inventory records.', 'success');
        loadFullInventoryPage();
        loadCanteenHomeData();

    } catch (err) {
        console.error('Error deleting inventory:', err);
        showToast('Failed to delete item.', 'danger');
    }
}

// --- 3.4 Food Redistribution & Inventory Reservation Engine ---
let currentSupplierRedistTab = 'posts';

function switchSupplierRedistTab(tab) {
    currentSupplierRedistTab = tab;
    const tabs = ['posts', 'requests', 'pickups', 'history'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-supplier-${t}`);
        const pane = document.getElementById(`supplier-tab-${t}-pane`);
        if (btn) {
            if (t === tab) btn.classList.add('active');
            else btn.classList.remove('active');
        }
        if (pane) {
            if (t === tab) pane.classList.remove('hidden');
            else pane.classList.add('hidden');
        }
    });
}

async function loadCanteenRecoveryTable() {
    try {
        const [postsRes, reqsRes, surplusRes] = await Promise.all([
            fetch(`${API_BASE}/api/redistribution/posts`),
            fetch(`${API_BASE}/api/redistribution/requests`),
            fetch(`${API_BASE}/api/surplus`)
        ]);

        let posts = [];
        let requests = [];

        if (postsRes.ok) {
            const data = await postsRes.json();
            posts = data.posts || [];
            renderSupplierPostsTable(posts);
        }

        if (reqsRes.ok) {
            const data = await reqsRes.json();
            requests = data.requests || [];
            renderSupplierRequestsTable(requests);
            renderSupplierPickupsTable(requests);
            renderSupplierHistoryTable(requests);
        }

        if (surplusRes.ok) {
            const data = await surplusRes.json();
            cachedSurplus = data.surplus_items || [];
            renderCanteenSurplusCards(cachedSurplus);
        }

        // Update tab count badges
        const postsCount = document.getElementById('supplier-posts-count');
        const reqsCount = document.getElementById('supplier-requests-count');
        const pickupsCount = document.getElementById('supplier-pickups-count');

        const activePostsCount = posts.filter(p => p.status === 'ACTIVE' || p.remaining_available > 0).length;
        const pendingReqsCount = requests.filter(r => r.status === 'PENDING').length;
        const scheduledPickupsCount = requests.filter(r => r.status === 'SCHEDULED' || r.status === 'ACCEPTED').length;

        if (postsCount) postsCount.textContent = activePostsCount;
        if (reqsCount) reqsCount.textContent = pendingReqsCount;
        if (pickupsCount) pickupsCount.textContent = scheduledPickupsCount;

    } catch (err) {
        console.error('Error loading supplier redistribution tables:', err);
    }
}

function renderSupplierPostsTable(posts) {
    const tbody = document.getElementById('supplier-posts-tbody');
    if (!tbody) return;

    if (!posts || posts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No surplus food currently published. Click "Publish Surplus Food" above to post available stock.</td></tr>`;
        return;
    }

    tbody.innerHTML = posts.map(post => {
        const isFullyReserved = post.remaining_available <= 0;
        const statusBadge = isFullyReserved
            ? `<span class="badge badge-warning">Fully Reserved</span>`
            : `<span class="badge badge-success">Available (${post.remaining_available} ${post.unit})</span>`;

        const pubTime = post.created_at ? new Date(post.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Today';

        return `
            <tr>
                <td><strong>${post.food_item}</strong></td>
                <td>${post.published_quantity} ${post.unit}</td>
                <td><strong style="color: var(--warning-text);">${post.reserved_quantity || 0} ${post.unit}</strong></td>
                <td><strong style="color: var(--success-text); font-size: 1.05rem;">${post.remaining_available} ${post.unit}</strong></td>
                <td><span class="badge badge-warning">${post.available_until || 'Today 4:00 PM'}</span></td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">${post.pickup_location || 'Canteen Gate 2'}</td>
                <td style="font-size: 0.82rem; color: var(--text-muted);">${pubTime}</td>
                <td>${statusBadge}</td>
            </tr>
        `;
    }).join('');
}

function renderSupplierRequestsTable(requests) {
    const tbody = document.getElementById('supplier-requests-tbody');
    if (!tbody) return;

    const pendingRequests = requests.filter(r => r.status === 'PENDING');

    if (pendingRequests.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No pending organization requests right now. All requests have been addressed.</td></tr>`;
        return;
    }

    tbody.innerHTML = pendingRequests.map(r => {
        const reqTime = r.requested_at ? new Date(r.requested_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Today';

        return `
            <tr>
                <td><strong>${r.organization_name}</strong></td>
                <td><strong>${r.food_item}</strong></td>
                <td><strong style="color: var(--primary); font-size: 1.05rem;">${r.requested_quantity} ${r.unit}</strong></td>
                <td style="font-size: 0.82rem; color: var(--text-muted);">${reqTime}</td>
                <td><span class="badge badge-warning">PENDING (HELD)</span></td>
                <td style="font-size: 0.82rem; color: var(--text-secondary); max-width: 200px;">
                    <div>${r.message || 'Standard request'}</div>
                    ${r.preferred_pickup_time ? `<div style="color: var(--primary); margin-top: 2px;">Prefers: ${r.preferred_pickup_time}</div>` : ''}
                </td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn-primary" style="padding: 4px 10px; font-size: 0.78rem; background: var(--success); border-color: var(--success);" onclick="handleSupplierAcceptRequest(${r.id})">
                            <i class="ph ph-check-circle"></i> Accept
                        </button>
                        <button class="btn-secondary" style="padding: 4px 10px; font-size: 0.78rem; color: var(--danger); border-color: rgba(239, 68, 68, 0.3);" onclick="handleSupplierRejectRequest(${r.id})">
                            <i class="ph ph-x-circle"></i> Reject
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function renderSupplierPickupsTable(requests) {
    const tbody = document.getElementById('supplier-pickups-tbody');
    if (!tbody) return;

    const pickups = requests.filter(r => r.status === 'SCHEDULED' || r.status === 'ACCEPTED' || r.status === 'COLLECTED');

    if (pickups.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No pickups currently scheduled. Accept an incoming request and assign a pickup schedule.</td></tr>`;
        return;
    }

    tbody.innerHTML = pickups.map(r => {
        let badge = `<span class="badge badge-info">ACCEPTED</span>`;
        let actionBtn = `
            <button class="btn-primary" style="padding: 4px 10px; font-size: 0.78rem;" onclick="openSchedulePickupModal(${r.id}, '${r.organization_name.replace(/'/g, "\\'")}', '${r.food_item.replace(/'/g, "\\'")}', ${r.requested_quantity}, '${r.unit}')">
                <i class="ph ph-calendar-plus"></i> Schedule Pickup
            </button>
        `;

        if (r.status === 'SCHEDULED') {
            badge = `<span class="badge badge-warning">SCHEDULED</span>`;
            actionBtn = `
                <button class="btn-primary" style="padding: 4px 10px; font-size: 0.78rem; background: var(--primary);" onclick="handleSupplierMarkCollected(${r.id})">
                    <i class="ph ph-check"></i> Mark Collected
                </button>
            `;
        } else if (r.status === 'COLLECTED') {
            badge = `<span class="badge badge-success">COLLECTED</span>`;
            actionBtn = `
                <button class="btn-primary" style="padding: 4px 10px; font-size: 0.78rem; background: var(--success); border-color: var(--success);" onclick="handleSupplierMarkCompleted(${r.id})">
                    <i class="ph ph-seal-check"></i> Mark Completed
                </button>
            `;
        }

        return `
            <tr>
                <td><strong>${r.organization_name}</strong></td>
                <td><strong>${r.food_item}</strong></td>
                <td>${r.requested_quantity} ${r.unit}</td>
                <td><strong>${r.pickup_date || 'Today'}</strong></td>
                <td><strong style="color: var(--primary);">${r.pickup_time || r.preferred_pickup_time || '2:00 PM'}</strong></td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">${r.pickup_location || 'Srinivas Campus Canteen'}</td>
                <td>${badge}</td>
                <td>${actionBtn}</td>
            </tr>
        `;
    }).join('');
}

function renderSupplierHistoryTable(requests) {
    const tbody = document.getElementById('supplier-history-tbody');
    if (!tbody) return;

    const history = requests.filter(r => r.status === 'COMPLETED' || r.status === 'REJECTED' || r.status === 'CANCELLED');

    if (history.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No completed or closed transactions yet. Completed donations will appear here.</td></tr>`;
        return;
    }

    tbody.innerHTML = history.map(r => {
        const isSuccess = r.status === 'COMPLETED';
        const badge = isSuccess ? `<span class="badge badge-success">COMPLETED</span>` : `<span class="badge badge-danger">${r.status}</span>`;
        const timeStr = r.completed_at ? new Date(r.completed_at).toLocaleString() : (r.accepted_at ? new Date(r.accepted_at).toLocaleString() : 'Recorded today');

        return `
            <tr>
                <td style="font-size: 0.82rem; color: var(--text-muted);">${timeStr}</td>
                <td><strong>${r.organization_name}</strong></td>
                <td><strong>${r.food_item}</strong></td>
                <td>${r.requested_quantity} ${r.unit}</td>
                <td>${badge}</td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">
                    ${isSuccess ? `Recovered & verified distribution. Pickup completed at ${r.pickup_location || 'Canteen'}.` : 'Request rejected; reserved stock released back to availability.'}
                </td>
            </tr>
        `;
    }).join('');
}

function renderCanteenSurplusCards(items) {
    const grid = document.getElementById('canteen-surplus-items-grid');
    if (!grid) return;

    if (!items || items.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 1.5rem; color: var(--text-muted);">
                <i class="ph ph-check-circle" style="font-size: 2rem; color: var(--success); display: block; margin-bottom: 0.5rem;"></i>
                <strong>No excess surplus detected in inventory at this time.</strong>
                <p style="font-size: 0.82rem; margin: 4px 0 0 0;">Kitchen stock is within expected daily consumption buffers. You can also publish manual batches anytime.</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = items.map(item => `
        <div class="card" style="margin: 0; padding: 1.1rem; border: 1px solid var(--border-color); background: var(--bg-card);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                <div>
                    <h4 style="font-size: 1rem; font-weight: 700; color: var(--text-primary); margin: 0;">${item.item_name || item.name}</h4>
                    <span style="font-size: 0.75rem; color: var(--text-muted);">${item.category || 'Cooked Meals'}</span>
                </div>
                <span class="badge badge-warning">${item.expiry_days <= 2 ? 'Near Expiry' : 'Surplus Stock'}</span>
            </div>
            <div style="font-size: 0.82rem; color: var(--text-secondary); margin: 0.5rem 0;">
                <div><strong>Available:</strong> ${item.quantity} ${item.unit}</div>
                <div><strong>Shelf Life:</strong> ${item.expiry_days} days remaining</div>
                <div style="color: var(--primary); margin-top: 2px;"><strong>Reason:</strong> ${item.surplus_reason || 'Batch exceeds planned daily consumption'}</div>
            </div>
            <button class="btn-primary btn-full" style="padding: 0.45rem; font-size: 0.8rem; background: var(--success); border-color: var(--success); margin-top: 0.5rem;" onclick="openPublishSurplusModal({ id: ${item.id}, name: '${(item.item_name || item.name).replace(/'/g, "\\'")}', qty: ${item.quantity}, unit: '${item.unit}' })">
                <i class="ph ph-broadcast"></i> Publish for All NGOs
            </button>
        </div>
    `).join('');
}

// Supplier Modal Controllers
function openPublishSurplusModal(prefill = null) {
    const modal = document.getElementById('publish-surplus-modal');
    if (!modal) return;

    const invIdInput = document.getElementById('pub-inv-id');
    const foodItemInput = document.getElementById('pub-food-item');
    const qtyInput = document.getElementById('pub-quantity');
    const unitSelect = document.getElementById('pub-unit');

    if (prefill) {
        if (invIdInput) invIdInput.value = prefill.id || '';
        if (foodItemInput) foodItemInput.value = prefill.name || '';
        if (qtyInput) qtyInput.value = prefill.qty || '';
        if (unitSelect && prefill.unit) unitSelect.value = prefill.unit;
    } else {
        if (invIdInput) invIdInput.value = '';
        if (foodItemInput) foodItemInput.value = '';
        if (qtyInput) qtyInput.value = '';
    }

    modal.classList.add('active');
}

function closePublishSurplusModal() {
    const modal = document.getElementById('publish-surplus-modal');
    if (modal) modal.classList.remove('active');
}

async function submitPublishSurplus(event) {
    if (event) event.preventDefault();
    const invId = document.getElementById('pub-inv-id')?.value;
    const food_item = document.getElementById('pub-food-item')?.value.trim();
    const published_quantity = parseFloat(document.getElementById('pub-quantity')?.value);
    const unit = document.getElementById('pub-unit')?.value || 'kg';
    const available_until = document.getElementById('pub-available-until')?.value.trim() || 'Today before 4:00 PM';
    const pickup_location = document.getElementById('pub-pickup-location')?.value.trim() || 'Srinivas Campus Canteen Gate 2, Mangalore';
    const notes = document.getElementById('pub-notes')?.value.trim() || 'Freshly prepared';

    if (!food_item || isNaN(published_quantity) || published_quantity <= 0) {
        showToast('Please specify a valid food item and quantity.', 'danger');
        return;
    }

    try {
        const payload = {
            inventory_id: invId ? parseInt(invId) : null,
            food_item,
            published_quantity,
            unit,
            available_until,
            pickup_location,
            notes,
            supplier_name: 'Srinivas Institute Canteen'
        };

        const res = await fetch(`${API_BASE}/api/redistribution/posts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to publish surplus food');

        showToast(`Published ${published_quantity} ${unit} of ${food_item} to all partner organizations!`, 'success');
        closePublishSurplusModal();
        loadCanteenRecoveryTable();
        loadCanteenHomeData();

    } catch (err) {
        console.error('Error publishing surplus:', err);
        showToast(err.message || 'Error publishing surplus.', 'danger');
    }
}

// Supplier Actions on Incoming Requests
async function handleSupplierAcceptRequest(requestId) {
    try {
        const res = await fetch(`${API_BASE}/api/redistribution/requests/${requestId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'ACCEPTED' })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to accept request');

        showToast('Request accepted! Quantity is permanently allocated to this organization.', 'success');
        loadCanteenRecoveryTable();
        switchSupplierRedistTab('pickups');

        // Automatically prompt pickup schedule modal
        const req = data.request;
        if (req) {
            openSchedulePickupModal(req.id, req.organization_name, req.food_item, req.requested_quantity, req.unit);
        }

    } catch (err) {
        console.error('Error accepting request:', err);
        showToast(err.message || 'Failed to accept request.', 'danger');
    }
}

async function handleSupplierRejectRequest(requestId) {
    if (!confirm('Reject this food request? The reserved quantity will immediately be released back into available inventory.')) return;

    try {
        const res = await fetch(`${API_BASE}/api/redistribution/requests/${requestId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'REJECTED' })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to reject request');

        showToast('Request rejected. Reserved quantity returned to available stock.', 'info');
        loadCanteenRecoveryTable();

    } catch (err) {
        console.error('Error rejecting request:', err);
        showToast(err.message || 'Failed to reject request.', 'danger');
    }
}

function openSchedulePickupModal(requestId, orgName, foodItem, quantity, unit) {
    const modal = document.getElementById('schedule-pickup-modal');
    if (!modal) return;

    const idInput = document.getElementById('sched-request-id');
    const orgEl = document.getElementById('sched-modal-org');
    const itemEl = document.getElementById('sched-modal-item');
    const dateInput = document.getElementById('sched-pickup-date');

    if (idInput) idInput.value = requestId;
    if (orgEl) orgEl.textContent = orgName;
    if (itemEl) itemEl.textContent = `${foodItem} (${quantity} ${unit})`;
    if (dateInput) {
        const todayStr = new Date().toISOString().split('T')[0];
        dateInput.value = todayStr;
    }

    modal.classList.add('active');
}

function closeSchedulePickupModal() {
    const modal = document.getElementById('schedule-pickup-modal');
    if (modal) modal.classList.remove('active');
}

async function submitSchedulePickup(event) {
    if (event) event.preventDefault();
    const requestId = parseInt(document.getElementById('sched-request-id')?.value);
    const pickup_date = document.getElementById('sched-pickup-date')?.value;
    const pickup_time = document.getElementById('sched-pickup-time')?.value.trim() || '2:00 PM';
    const pickup_location = document.getElementById('sched-pickup-location')?.value.trim() || 'Srinivas Campus Canteen Gate 2, Mangalore';

    if (!requestId || !pickup_date || !pickup_time) {
        showToast('Please provide pickup date and time.', 'danger');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/redistribution/requests/${requestId}/schedule`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pickup_date, pickup_time, pickup_location })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to schedule pickup');

        showToast(`Pickup scheduled for ${pickup_date} at ${pickup_time}! Partner organization notified.`, 'success');
        closeSchedulePickupModal();
        loadCanteenRecoveryTable();

    } catch (err) {
        console.error('Error scheduling pickup:', err);
        showToast(err.message || 'Error scheduling pickup.', 'danger');
    }
}

async function handleSupplierMarkCollected(requestId) {
    try {
        const res = await fetch(`${API_BASE}/api/redistribution/requests/${requestId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'COLLECTED' })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to mark collected');

        showToast('Donation marked as COLLECTED. Handover verified.', 'info');
        loadCanteenRecoveryTable();

    } catch (err) {
        console.error('Error marking collected:', err);
        showToast(err.message || 'Failed to update status.', 'danger');
    }
}

async function handleSupplierMarkCompleted(requestId) {
    try {
        const res = await fetch(`${API_BASE}/api/redistribution/requests/${requestId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'COMPLETED' })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to mark completed');

        showToast('Donation transaction marked COMPLETED and archived to history!', 'success');
        loadCanteenRecoveryTable();
        switchSupplierRedistTab('history');

    } catch (err) {
        console.error('Error marking completed:', err);
        showToast(err.message || 'Failed to complete transaction.', 'danger');
    }
}

// Backward Compatibility Aliases for Legacy Modals
function openSurplusDonationModal() {
    openPublishSurplusModal();
}

function openSurplusDonationModalWithItem(itemId) {
    const item = cachedInventory.find(i => i.id === itemId);
    if (item) {
        openPublishSurplusModal({ id: item.id, name: item.name || item.item_name, qty: item.quantity, unit: item.unit });
    } else {
        openPublishSurplusModal();
    }
}

function closeSurplusDonationModal() {
    closePublishSurplusModal();
}

function submitSurplusDonation(event) {
    submitPublishSurplus(event);
}

// --- 3.5 Registered NGO Partners Directory & Interactive Map ---
let canteenNgoMap = null;
let canteenNgoMarkers = [];

async function loadCanteenNgos() {
    try {
        const res = await fetch(`${API_BASE}/api/ngos`);
        if (!res.ok) throw new Error('Failed to fetch NGOs');
        const data = await res.json();
        cachedNgos = data.ngos || [];
        renderNgoPartnersList();
        initCanteenNgoMap();
    } catch (err) {
        console.error('Error loading NGOs:', err);
    }
}

function initCanteenNgoMap() {
    const mapContainer = document.getElementById('canteen-ngo-map');
    if (!mapContainer || typeof L === 'undefined') return;

    const canteenCenter = [12.8718, 74.9204];

    if (!canteenNgoMap) {
        canteenNgoMap = L.map('canteen-ngo-map').setView(canteenCenter, 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 18,
            attribution: '© OpenStreetMap contributors'
        }).addTo(canteenNgoMap);
    } else {
        canteenNgoMarkers.forEach(m => canteenNgoMap.removeLayer(m));
        canteenNgoMarkers = [];
    }

    // Srinivas Canteen Hub marker
    const canteenIcon = L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background: #10b981; color: white; width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; box-shadow: 0 3px 8px rgba(0,0,0,0.3); border: 2px solid white;">🍳</div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17]
    });

    const cMarker = L.marker(canteenCenter, { icon: canteenIcon }).addTo(canteenNgoMap);
    cMarker.bindPopup(`
        <div style="font-family: inherit; padding: 4px;">
            <strong style="color: #059669; font-size: 1rem;">Srinivas Institute Canteen</strong><br>
            <span style="font-size: 0.8rem; color: #64748b;">Central Kitchen & Surplus Recovery Hub</span><br>
            <div style="margin-top: 6px; font-size: 0.8rem;">📍 Valachil Campus, Mangalore</div>
        </div>
    `);
    canteenNgoMarkers.push(cMarker);

    // Plot all NGOs
    if (cachedNgos && cachedNgos.length > 0) {
        cachedNgos.forEach(ngo => {
            const lat = parseFloat(ngo.latitude);
            const lon = parseFloat(ngo.longitude);
            if (isNaN(lat) || isNaN(lon)) return;

            const isHigh = (ngo.need_level || '').toLowerCase() === 'high';
            const vStatus = (ngo.verification_status || 'VERIFIED').toUpperCase();
            const iconEmoji = vStatus === 'VERIFIED' ? (isHigh ? '🚨' : '🍲') : '⏳';
            const iconBg = vStatus === 'VERIFIED' ? (isHigh ? '#ef4444' : '#3b82f6') : '#f59e0b';

            const ngoIcon = L.divIcon({
                className: 'custom-map-marker',
                html: `<div style="background: ${iconBg}; color: white; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 15px; box-shadow: 0 2px 6px rgba(0,0,0,0.25); border: 2px solid white;">${iconEmoji}</div>`,
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            });

            const marker = L.marker([lat, lon], { icon: ngoIcon }).addTo(canteenNgoMap);
            marker.bindPopup(`
                <div style="font-family: inherit; padding: 4px; min-width: 200px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                        <strong style="font-size: 0.95rem; color: #1e293b;">${ngo.name}</strong>
                    </div>
                    <div style="font-size: 0.78rem; margin: 4px 0;">
                        <span style="display: inline-block; padding: 2px 6px; border-radius: 4px; font-weight: 700; background: ${iconBg}20; color: ${iconBg};">
                            ${vStatus}
                        </span>
                        <span style="margin-left: 4px; color: #64748b;">${ngo.distance_km || 0} km away</span>
                    </div>
                    <div style="font-size: 0.8rem; color: #475569; line-height: 1.4;">
                        👥 Capacity: <strong>${ngo.capacity_persons || ngo.capacity_people || 150}</strong> people/day<br>
                        📞 ${ngo.phone || '+91 98450 12345'}<br>
                        📍 ${ngo.address || 'Mangalore'}
                    </div>
                </div>
            `);
            canteenNgoMarkers.push(marker);
        });
    }

    setTimeout(() => {
        if (canteenNgoMap) canteenNgoMap.invalidateSize();
    }, 200);
}

function renderNgoPartnersList() {
    const grid = document.getElementById('canteen-ngos-grid');
    if (!grid) return;

    const searchTerm = document.getElementById('ngo-partner-search')?.value.toLowerCase() || '';
    const needFilter = document.getElementById('ngo-partner-need-filter')?.value || 'all';

    const filtered = cachedNgos.filter(n => {
        const matchesSearch = n.name.toLowerCase().includes(searchTerm) || (n.address || '').toLowerCase().includes(searchTerm);
        const matchesNeed = needFilter === 'all' || (n.need_level || '').toLowerCase() === needFilter.toLowerCase();
        return matchesSearch && matchesNeed;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `<p class="text-muted" style="grid-column: 1 / -1; text-align: center;">No registered NGO partners match the filter.</p>`;
        return;
    }

    grid.innerHTML = filtered.map(ngo => {
        const isHigh = (ngo.need_level || '').toLowerCase() === 'high';
        const vStatus = (ngo.verification_status || 'VERIFIED').toUpperCase();

        let badgeHtml = '';
        if (vStatus === 'VERIFIED') {
            badgeHtml = `<span class="badge badge-success"><i class="ph ph-check-circle"></i> VERIFIED</span>`;
        } else if (vStatus === 'PENDING') {
            badgeHtml = `<span class="badge badge-warning" style="background: rgba(245, 158, 11, 0.15); color: #d97706; border: 1px solid rgba(245, 158, 11, 0.4);"><i class="ph ph-clock"></i> PENDING VERIFICATION</span>`;
        } else {
            badgeHtml = `<span class="badge badge-danger"><i class="ph ph-x-circle"></i> REJECTED</span>`;
        }

        let actionsHtml = '';
        if (vStatus === 'PENDING') {
            actionsHtml = `
                <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                    <button class="btn-primary" style="flex: 1; padding: 0.45rem; font-size: 0.8rem; background: var(--success); border-color: var(--success);" onclick="verifyNgoStatus(${ngo.id}, 'VERIFIED')">
                        <i class="ph ph-check-bold"></i> Approve Partner
                    </button>
                    <button class="btn-secondary" style="flex: 1; padding: 0.45rem; font-size: 0.8rem; color: var(--danger); border-color: var(--danger);" onclick="verifyNgoStatus(${ngo.id}, 'REJECTED')">
                        <i class="ph ph-x-bold"></i> Reject
                    </button>
                </div>
            `;
        } else if (vStatus === 'VERIFIED') {
            actionsHtml = `
                <button class="btn-primary btn-full" style="padding: 0.5rem; font-size: 0.82rem; margin-top: 0.75rem;" onclick="openSurplusDonationModalWithNgo(${ngo.id})">
                    <i class="ph ph-heart"></i> Dispatch Food Recovery
                </button>
            `;
        } else {
            actionsHtml = `
                <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                    <button class="btn-secondary btn-full" style="padding: 0.45rem; font-size: 0.8rem;" onclick="verifyNgoStatus(${ngo.id}, 'VERIFIED')">
                        <i class="ph ph-arrow-counter-clockwise"></i> Re-verify Partner
                    </button>
                </div>
            `;
        }

        return `
            <div class="card" style="margin: 0; padding: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem; gap: 0.5rem;">
                    <div>
                        <h3 style="font-size: 1.05rem; font-weight: 700; margin: 0; color: var(--text-primary);">${ngo.name}</h3>
                        <p style="font-size: 0.78rem; color: var(--text-muted); margin: 2px 0 0 0;"><i class="ph ph-map-pin"></i> ${ngo.distance_km || 1.5} km from Srinivas Campus</p>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem;">
                        <span class="badge ${isHigh ? 'badge-danger' : 'badge-warning'}">${(ngo.need_level || 'Medium').toUpperCase()} NEED</span>
                        ${badgeHtml}
                    </div>
                </div>
                <div style="background: var(--bg-body); padding: 0.75rem; border-radius: var(--radius-sm); font-size: 0.82rem; margin: 0.65rem 0;">
                    <div style="margin-bottom: 3px;"><strong>Capacity:</strong> ${ngo.capacity_persons || ngo.capacity_people || 150} people nourished daily</div>
                    <div style="margin-bottom: 3px;"><strong>Coordinator:</strong> ${ngo.contact_person || ngo.manager || 'Relief Coordinator'}</div>
                    <div style="margin-bottom: 3px;"><strong>Contact:</strong> ${ngo.phone || '+91 98450 12345'}</div>
                    <div><strong>Address:</strong> ${ngo.address || 'Mangalore'}</div>
                </div>
                ${actionsHtml}
            </div>
        `;
    }).join('');
}

async function verifyNgoStatus(ngoId, status) {
    try {
        const res = await fetch(`${API_BASE}/api/ngos/${ngoId}/verify`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.detail || 'Failed to update NGO verification status', 'error');
            return;
        }
        showToast(data.message || `Partner status updated to ${status}`, 'success');
        await loadCanteenNgos();
    } catch (err) {
        console.error('Error verifying NGO:', err);
        showToast('Server error updating NGO status', 'error');
    }
}


function openSurplusDonationModalWithNgo(ngoId) {
    openSurplusDonationModal().then(() => {
        const select = document.getElementById('donation-ngo-select');
        if (select) {
            select.value = ngoId;
        }
    });
}

// --- 3.6 Canteen Analytics & Category Breakdown ---
async function loadCanteenAnalytics() {
    try {
        const [dashRes, sumRes] = await Promise.all([
            fetch(`${API_BASE}/api/dashboard/canteen`),
            fetch(`${API_BASE}/api/dashboard/inventory-summary`)
        ]);

        if (dashRes.ok) {
            const data = await dashRes.json();
            const kpi = data.kpis;

            const elEff = document.getElementById('canteen-ana-prep-eff');
            const elOver = document.getElementById('canteen-ana-overprod');
            const elSaved = document.getElementById('canteen-ana-food-saved');
            const elCo2 = document.getElementById('canteen-ana-co2');

            if (elEff) elEff.textContent = `${kpi.operations.prep_efficiency_pct || 94}%`;
            if (elOver) elOver.textContent = `${kpi.operations.overproduction_avoided || 120} Servings`;
            if (elSaved) elSaved.textContent = `${(kpi.donations.food_saved_kg || 0).toLocaleString()} kg`;
            if (elCo2) elCo2.textContent = `${Math.round((kpi.donations.food_saved_kg || 0) * 2.1).toLocaleString()} kg`;
        }

        if (sumRes.ok) {
            const sumData = await sumRes.json();
            renderCanteenCategoryBars(sumData.categories || []);
        }

        try {
            const mlRes = await fetch(`${API_BASE}/api/ml/metrics`);
            if (mlRes.ok) {
                const mlData = await mlRes.json();
                const elMae = document.getElementById('ml-metric-mae');
                const elMape = document.getElementById('ml-metric-mape');
                const elR2 = document.getElementById('ml-metric-r2');
                const elRmse = document.getElementById('ml-metric-rmse');
                const elBadge = document.getElementById('ml-metric-samples-badge');

                if (elMae) elMae.textContent = 'LGBMRegressor';
                if (elMape) elMape.textContent = 'Quantile (α=0.85)';
                if (elR2) elR2.textContent = `${mlData.features_count || 19} Features`;
                if (elRmse) elRmse.textContent = mlData.status || 'ACTIVE';
                if (elBadge) elBadge.innerHTML = `<i class="ph ph-sliders"></i> ${mlData.features_count || 19} Features`;
            }
        } catch (mlErr) {
            console.warn('ML metrics fetch error:', mlErr);
        }

        initCanteenAnalyticsChart();

    } catch (err) {
        console.error('Error loading canteen analytics:', err);
    }
}

function renderCanteenCategoryBars(categories) {
    const container = document.getElementById('canteen-category-distribution-bars');
    if (!container) return;

    if (categories.length === 0) {
        container.innerHTML = `<p class="text-muted" style="font-size: 0.85rem;">No inventory records in MySQL.</p>`;
        return;
    }

    const colors = ['var(--primary)', 'var(--warning)', 'var(--accent)', 'var(--success)', '#8b5cf6'];
    container.innerHTML = categories.map((c, i) => `
        <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.84rem; font-weight: 600; margin-bottom: 4px;">
                <span>${c.category} (${c.count} items)</span>
                <span style="color: ${colors[i % colors.length]};">${c.percentage}%</span>
            </div>
            <div style="height: 8px; background: var(--border-color); border-radius: 4px; overflow: hidden;">
                <div style="width: ${c.percentage}%; height: 100%; background: ${colors[i % colors.length]};"></div>
            </div>
        </div>
    `).join('');
}

async function initCanteenAnalyticsChart() {
    const ctx = document.getElementById('canteenAnalyticsDemandChart');
    if (!ctx) return;

    let labels = [];
    let demandData = [];
    let prepData = [];

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/demand-trend?limit=7`);
        if (res.ok) {
            const data = await res.json();
            labels = data.labels || [];
            demandData = data.demand || [];
            prepData = data.recommended_prep || [];
        }
    } catch (e) {}

    if (labels.length === 0) {
        labels = ['Historical Data'];
        demandData = [0];
        prepData = [0];
    }

    if (canteenAnalyticsDemandChartInstance) {
        canteenAnalyticsDemandChartInstance.destroy();
    }

    canteenAnalyticsDemandChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Predicted Demand (Servings)',
                    data: demandData,
                    borderColor: '#2ca85b',
                    backgroundColor: 'rgba(44, 168, 91, 0.12)',
                    borderWidth: 2.5,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Recommended Batch Prep (Servings)',
                    data: prepData,
                    borderColor: '#65c885',
                    backgroundColor: 'rgba(101, 200, 133, 0.08)',
                    borderWidth: 2.5,
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', font: { family: 'Inter', size: 12, weight: 600 } } }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { family: 'Inter' } } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.08)' }, ticks: { color: '#94a3b8', font: { family: 'Inter' } }, beginAtZero: true }
            }
        }
    });
}

// --- 3.7 Canteen Announcements ---
async function loadCanteenAnnouncements() {
    try {
        const res = await fetch(`${API_BASE}/api/announcements`);
        if (!res.ok) throw new Error('Announcements fetch failed');
        const data = await res.json();
        cachedAnnouncements = data.announcements || [];
        renderCanteenAnnouncements(cachedAnnouncements);
    } catch (err) {
        console.error('Error loading announcements:', err);
    }
}

function renderCanteenAnnouncements(items) {
    const feed = document.getElementById('canteen-announcements-feed');
    if (!feed) return;

    if (items.length === 0) {
        feed.innerHTML = `<p class="text-muted" style="font-size: 0.85rem;">No notices dispatched yet.</p>`;
        return;
    }

    feed.innerHTML = items.map(ann => {
        const isUrgent = (ann.priority || '').toLowerCase() === 'urgent';
        return `
            <div style="border: 1px solid var(--border-color); padding: 1rem; border-radius: var(--radius-sm); background: var(--bg-card);">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.4rem;">
                    <h4 style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary); margin: 0;">${ann.title}</h4>
                    <span class="badge ${isUrgent ? 'badge-danger' : 'badge-info'}">${ann.priority}</span>
                </div>
                <p style="font-size: 0.85rem; color: var(--text-secondary); margin: 0.4rem 0 0.6rem 0;">${ann.message}</p>
                <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted);">
                    <span>Audience: <strong>${ann.recipient}</strong></span>
                    <span>${ann.status || 'Dispatched'}</span>
                </div>
            </div>
        `;
    }).join('');
}

const canteenAnnForm = document.getElementById('canteen-announcement-form');
if (canteenAnnForm) {
    canteenAnnForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const title = document.getElementById('canteen-ann-title')?.value.trim();
        const recipient = document.getElementById('canteen-ann-recipient')?.value;
        const priority = document.getElementById('canteen-ann-priority')?.value;
        const message = document.getElementById('canteen-ann-message')?.value.trim();

        try {
            const res = await fetch(`${API_BASE}/api/announcements`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    recipient,
                    priority,
                    message,
                    sender: 'Canteen Staff'
                })
            });

            if (!res.ok) throw new Error('Announcement failed');

            showToast('Staff notice dispatched & recorded in MySQL!', 'success');
            canteenAnnForm.reset();
            loadCanteenAnnouncements();

        } catch (err) {
            showToast('Failed to post announcement.', 'danger');
        }
    });
}


// =========================================================================
// 4. NGO / RELIEF PARTNER WORKSPACE LOGIC
// =========================================================================

// --- 4.1 NGO Home Command Center (Strict Data Isolation) ---
async function loadNgoHomeData() {
    const auth = getAuth();
    if (!auth) return;
    const ngoId = auth.ngo_id || auth.id;

    const greetingEl = document.getElementById('ngo-home-greeting-name');
    const orgBadge = document.getElementById('ngo-home-org-badge');
    if (greetingEl) greetingEl.textContent = auth.name || 'Relief Coordinator';
    if (orgBadge) orgBadge.textContent = auth.organization || 'Registered NGO';

    try {
        const [postsRes, reqsRes, dashRes] = await Promise.all([
            authFetch(`${API_BASE}/api/redistribution/posts?available_only=true`),
            authFetch(`${API_BASE}/api/redistribution/requests?organization_id=${ngoId}`),
            authFetch(`${API_BASE}/api/dashboard/ngo?ngo_id=${ngoId}`)
        ]);

        let availablePosts = [];
        let myRequests = [];
        let dashKpis = null;

        if (postsRes.ok) {
            const data = await postsRes.json();
            availablePosts = data.posts || [];
        }

        if (reqsRes.ok) {
            const data = await reqsRes.json();
            myRequests = data.requests || [];
        }

        if (dashRes.ok) {
            const dashData = await dashRes.json();
            dashKpis = dashData.kpis || {};
            if (dashData.ngo_name && orgBadge) {
                orgBadge.textContent = dashData.ngo_name;
            }
        }

        // Authoritative Database Counts strictly for this authenticated organization
        const totalReqs = dashKpis ? (dashKpis.total_requests ?? myRequests.length) : myRequests.length;
        const pendingCount = dashKpis ? (dashKpis.pending_requests ?? dashKpis.incoming_pending ?? 0) : myRequests.filter(r => r.status === 'PENDING').length;
        const acceptedCount = dashKpis ? (dashKpis.accepted_requests ?? 0) : myRequests.filter(r => r.status === 'ACCEPTED' || r.status === 'SCHEDULED').length;
        const completedCount = dashKpis ? (dashKpis.completed_requests ?? dashKpis.completed_donations ?? 0) : myRequests.filter(r => r.status === 'COMPLETED' || r.status === 'COLLECTED').length;
        const totalReceivedKg = dashKpis ? parseFloat(dashKpis.food_received_kg ?? 0) : myRequests.filter(r => r.status === 'COMPLETED' || r.status === 'COLLECTED').reduce((sum, r) => sum + (parseFloat(r.requested_quantity) || 0), 0);
        const mealsProvided = dashKpis ? parseInt(dashKpis.meals_provided ?? dashKpis.meals_distributed ?? Math.round(totalReceivedKg * 2.5), 10) : Math.round(totalReceivedKg * 2.5);
        const batchesCount = dashKpis ? (dashKpis.available_surplus_batches ?? availablePosts.length) : availablePosts.length;

        // Update NGO Home KPIs (Dynamic from MySQL, zero hardcoding)
        const elSurplus = document.getElementById('ngo-home-surplus');
        const elIncoming = document.getElementById('ngo-home-incoming');
        const elAccepted = document.getElementById('ngo-home-accepted');
        const elReceived = document.getElementById('ngo-home-received');
        const elMealsBadge = document.getElementById('ngo-home-meals-badge');

        if (elSurplus) elSurplus.textContent = `${batchesCount} Batches`;
        if (elIncoming) elIncoming.textContent = `${pendingCount} Requests`;
        if (elAccepted) elAccepted.textContent = `${acceptedCount} Scheduled`;
        if (elReceived) elReceived.textContent = `${totalReceivedKg.toFixed(1)} kg`;
        if (elMealsBadge) elMealsBadge.textContent = `${mealsProvided} Meals`;

        // Verified Relief Impact Numbers
        const impMeals = document.getElementById('ngo-impact-meals');
        const impBen = document.getElementById('ngo-impact-beneficiaries');
        const impWaste = document.getElementById('ngo-impact-waste');
        const impRate = document.getElementById('ngo-impact-rate');

        if (impMeals) impMeals.textContent = (dashKpis?.impact?.meals_provided ?? mealsProvided).toLocaleString();
        if (impBen) impBen.textContent = (dashKpis?.impact?.people_nourished ?? Math.round(mealsProvided * 0.7)).toLocaleString();
        if (impWaste) impWaste.textContent = `${(dashKpis?.impact?.waste_diverted_kg ?? totalReceivedKg).toFixed(1)} kg`;
        if (impRate) {
            const acceptanceRate = dashKpis?.impact?.acceptance_rate_pct ?? (totalReqs > 0 ? Math.round(((acceptedCount + completedCount) / totalReqs) * 100) : 100);
            impRate.textContent = `${acceptanceRate}%`;
        }

        // Render Action Required Banner
        renderNgoActionRequiredCards(myRequests, availablePosts);

        // Render Available Food Preview on Home
        renderNgoHomeAvailablePreview(availablePosts);

    } catch (err) {
        console.error('Error loading NGO home data:', err);
    }
}

function renderNgoActionRequiredCards(myRequests, availablePosts) {
    const container = document.getElementById('ngo-actions-required-container');
    if (!container) return;

    const scheduled = myRequests.filter(r => r.status === 'SCHEDULED');
    const pending = myRequests.filter(r => r.status === 'PENDING');

    if (scheduled.length === 0 && pending.length === 0 && availablePosts.length === 0) {
        container.innerHTML = `
            <div style="background: var(--bg-body); border-left: 4px solid var(--success); padding: 1rem; border-radius: var(--radius-sm); display: flex; align-items: center; gap: 0.75rem;">
                <i class="ph ph-check-circle" style="font-size: 1.5rem; color: var(--success);"></i>
                <div>
                    <h4 style="font-size: 0.92rem; font-weight: 700; margin: 0; color: var(--text-primary);">All Operations Up to Date</h4>
                    <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 2px 0 0 0;">No active pickups or pending requests currently awaiting your action.</p>
                </div>
            </div>
        `;
        return;
    }

    let itemsHtml = '';

    if (scheduled.length > 0) {
        itemsHtml += scheduled.map(s => `
            <div class="action-required-card warning" style="margin-bottom: 0.5rem;">
                <div>
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 3px;">
                        <span class="badge badge-warning">Pickup Scheduled</span>
                        <strong style="font-size: 0.95rem; color: var(--text-primary);">${s.food_item} (${s.requested_quantity} ${s.unit})</strong>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary); display: flex; gap: 1rem; flex-wrap: wrap;">
                        <span><i class="ph ph-calendar"></i> Date: <strong>${s.pickup_date || 'Today'}</strong></span>
                        <span><i class="ph ph-clock"></i> Time: <strong>${s.pickup_time || '2:00 PM'}</strong></span>
                        <span><i class="ph ph-map-pin"></i> ${s.pickup_location || 'Srinivas Canteen'}</span>
                    </div>
                </div>
                <button class="btn-primary" style="padding: 0.4rem 0.8rem; font-size: 0.78rem;" onclick="navigateTo('ngo-schedule')">
                    View Pickup →
                </button>
            </div>
        `).join('');
    }

    if (availablePosts.length > 0) {
        const topPost = availablePosts[0];
        itemsHtml += `
            <div class="action-required-card success">
                <div>
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 3px;">
                        <span class="badge badge-success">Fresh Surplus Available</span>
                        <strong style="font-size: 0.95rem; color: var(--text-primary);">${topPost.food_item}</strong>
                        <span style="font-size: 0.82rem; color: var(--success-text); font-weight: 700;">(${topPost.remaining_available} ${topPost.unit} available)</span>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">
                        Published by Srinivas Canteen. Available until ${topPost.available_until || '4:00 PM'}.
                    </div>
                </div>
                <button class="btn-primary" style="padding: 0.4rem 0.8rem; font-size: 0.78rem; background: var(--success); border-color: var(--success);" onclick="openRequestFoodModal(${topPost.id})">
                    <i class="ph ph-hand-heart"></i> Request Food
                </button>
            </div>
        `;
    }

    container.innerHTML = itemsHtml;
}

function renderNgoHomeAvailablePreview(availablePosts) {
    const tbody = document.getElementById('ngo-home-donations-tbody');
    if (!tbody) return;

    if (!availablePosts || availablePosts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No surplus food currently available. Check back soon for new batches.</td></tr>`;
        return;
    }

    tbody.innerHTML = availablePosts.slice(0, 5).map(p => {
        const isAvail = p.remaining_available > 0;
        return `
            <tr>
                <td><strong>${p.supplier_name || 'Srinivas Canteen'}</strong></td>
                <td><strong>${p.food_item}</strong></td>
                <td><strong style="color: var(--success-text);">${p.remaining_available} ${p.unit}</strong></td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">${p.pickup_location || 'Canteen Gate 2'}</td>
                <td><span class="badge badge-warning">${p.available_until || 'Today 4:00 PM'}</span></td>
                <td><span class="badge ${isAvail ? 'badge-success' : 'badge-warning'}">${isAvail ? 'Available' : 'Reserved'}</span></td>
                <td>
                    ${isAvail ? `
                        <button class="btn-primary" style="padding: 3px 10px; font-size: 0.78rem; background: var(--success); border-color: var(--success);" onclick="openRequestFoodModal(${p.id})">
                            <i class="ph ph-hand-heart"></i> Request
                        </button>
                    ` : `<span style="font-size: 0.75rem; color: var(--text-muted);">Fully Held</span>`}
                </td>
            </tr>
        `;
    }).join('');
}

// --- 4.2 Available Food Common Feed (Visible to ALL NGOs) ---
async function loadNgoIncomingPage() {
    const grid = document.getElementById('ngo-available-posts-grid');
    if (!grid) return;

    try {
        const res = await fetch(`${API_BASE}/api/redistribution/posts`);
        if (!res.ok) throw new Error('Failed to fetch available surplus posts');
        const data = await res.json();
        const posts = data.posts || [];

        if (posts.length === 0) {
            grid.innerHTML = `
                <div class="card text-center text-muted" style="grid-column: 1 / -1; padding: 3rem 1rem;">
                    <i class="ph ph-plant" style="font-size: 2.5rem; color: var(--success); opacity: 0.7; margin-bottom: 0.5rem; display: block;"></i>
                    <h3 style="font-size: 1.1rem; color: var(--text-primary); margin-bottom: 0.25rem;">No Surplus Food Currently Published</h3>
                    <p style="font-size: 0.85rem; max-width: 400px; margin: 0 auto; color: var(--text-secondary);">
                        When Srinivas Institute Canteen identifies excess food batches, they will appear here live for all registered partner organizations to request.
                    </p>
                </div>
            `;
            return;
        }

        grid.innerHTML = posts.map(p => {
            const remaining = parseFloat(p.remaining_available) || 0;
            const reserved = parseFloat(p.reserved_quantity) || 0;
            const total = parseFloat(p.published_quantity) || 0;
            const isFullyReserved = remaining <= 0;

            return `
                <div class="food-post-card ${isFullyReserved ? 'fully-reserved' : ''}">
                    <div>
                        <div class="food-post-header">
                            <div>
                                <h3 class="food-post-title">${p.food_item}</h3>
                                <div class="food-post-supplier">
                                    <i class="ph ph-storefront"></i>
                                    <span>${p.supplier_name || 'Srinivas Institute Canteen, Mangalore'}</span>
                                </div>
                            </div>
                            <span class="badge ${isFullyReserved ? 'badge-warning' : 'badge-success'}">
                                ${isFullyReserved ? 'Fully Reserved' : 'Available Now'}
                            </span>
                        </div>

                        <!-- Dynamic Quantities Grid -->
                        <div class="food-post-quantities">
                            <div class="qty-stat-box">
                                <span class="qty-stat-label">Currently Available</span>
                                <span class="qty-stat-val ${isFullyReserved ? 'reserved' : 'available'}">${remaining} ${p.unit}</span>
                            </div>
                            <div class="qty-stat-box">
                                <span class="qty-stat-label">Total Published</span>
                                <span class="qty-stat-val" style="font-size: 0.95rem; color: var(--text-secondary);">${total} ${p.unit} (${reserved} ${p.unit} held)</span>
                            </div>
                        </div>

                        <div class="food-post-meta">
                            <div class="food-post-meta-row">
                                <i class="ph ph-clock text-warning"></i>
                                <span>Available Until: <strong>${p.available_until || 'Today 4:00 PM'}</strong></span>
                            </div>
                            <div class="food-post-meta-row">
                                <i class="ph ph-map-pin text-primary"></i>
                                <span>Pickup: <strong>${p.pickup_location || 'Srinivas Campus Canteen Gate 2'}</strong></span>
                            </div>
                            ${p.notes ? `
                                <div class="food-post-meta-row" style="color: var(--text-muted); font-style: italic;">
                                    <i class="ph ph-info"></i>
                                    <span>${p.notes}</span>
                                </div>
                            ` : ''}
                        </div>
                    </div>

                    <div style="margin-top: 0.75rem;">
                        ${isFullyReserved ? `
                            <button class="btn-secondary btn-full" disabled style="opacity: 0.6; cursor: not-allowed;">
                                <i class="ph ph-lock"></i> All Quantity Currently Reserved
                            </button>
                        ` : `
                            <button class="btn-primary btn-full" style="background: var(--success); border-color: var(--success);" onclick="openRequestFoodModal(${p.id})">
                                <i class="ph ph-hand-heart"></i> Request Food (${remaining} ${p.unit} remaining)
                            </button>
                        `}
                    </div>
                </div>
            `;
        }).join('');

    } catch (err) {
        console.error('Error loading available food feed:', err);
        grid.innerHTML = `<div class="card text-center text-muted" style="grid-column: 1 / -1; padding: 2rem;">Failed to load available food from MySQL.</div>`;
    }
}

// Request Food Modal (NGO Requesting from Supplier)
let activeRequestPost = null;

async function openRequestFoodModal(postId) {
    const modal = document.getElementById('request-food-modal');
    if (!modal) return;

    try {
        const res = await fetch(`${API_BASE}/api/redistribution/posts/${postId}`);
        if (!res.ok) throw new Error('Post not found');
        const data = await res.json();
        const post = data.post;
        activeRequestPost = post;

        const idInput = document.getElementById('req-post-id');
        const foodTitle = document.getElementById('req-modal-food-item');
        const availBadge = document.getElementById('req-modal-avail-badge');
        const supEl = document.getElementById('req-modal-supplier');
        const deadEl = document.getElementById('req-modal-deadline');
        const pickEl = document.getElementById('req-modal-pickup');
        const unitLabel = document.getElementById('req-modal-unit-label');
        const maxLabel = document.getElementById('req-modal-max-label');
        const qtyInput = document.getElementById('req-modal-quantity');
        const errAlert = document.getElementById('req-modal-error-alert');

        if (idInput) idInput.value = post.id;
        if (foodTitle) foodTitle.textContent = post.food_item;
        if (availBadge) availBadge.textContent = `${post.remaining_available} ${post.unit} available`;
        if (supEl) supEl.textContent = post.supplier_name || 'Srinivas Institute Canteen';
        if (deadEl) deadEl.textContent = post.available_until || 'Today 4:00 PM';
        if (pickEl) pickEl.textContent = post.pickup_location || 'Srinivas Canteen Gate 2';
        if (unitLabel) unitLabel.textContent = post.unit;
        if (maxLabel) maxLabel.textContent = `${post.remaining_available} ${post.unit}`;

        if (qtyInput) {
            qtyInput.max = post.remaining_available;
            qtyInput.value = Math.min(10, post.remaining_available);
            qtyInput.min = 0.5;
        }

        if (errAlert) {
            errAlert.classList.add('hidden');
            errAlert.textContent = '';
        }

        modal.classList.add('active');

    } catch (e) {
        console.error('Error opening request modal:', e);
        showToast('Unable to open food request details.', 'danger');
    }
}

function closeRequestFoodModal() {
    const modal = document.getElementById('request-food-modal');
    if (modal) modal.classList.remove('active');
    activeRequestPost = null;
}

async function submitRequestFood(event) {
    if (event) event.preventDefault();
    const auth = getAuth();
    if (!auth) {
        showToast('Please sign in to submit a food request.', 'danger');
        navigateTo('login');
        return;
    }

    const postId = parseInt(document.getElementById('req-post-id')?.value);
    const requestedQty = parseFloat(document.getElementById('req-modal-quantity')?.value);
    const pickupTime = document.getElementById('req-modal-pickup-time')?.value.trim() || 'Today 2:00 PM';
    const message = document.getElementById('req-modal-message')?.value.trim() || '';
    const errAlert = document.getElementById('req-modal-error-alert');
    const submitBtn = document.getElementById('req-modal-submit-btn');

    if (!postId || isNaN(requestedQty) || requestedQty <= 0) {
        if (errAlert) {
            errAlert.textContent = 'Please enter a valid requested quantity greater than 0.';
            errAlert.classList.remove('hidden');
        }
        return;
    }

    if (activeRequestPost && requestedQty > activeRequestPost.remaining_available) {
        if (errAlert) {
            errAlert.textContent = `Only ${activeRequestPost.remaining_available} ${activeRequestPost.unit} is currently available.`;
            errAlert.classList.remove('hidden');
        }
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="ph ph-spinner ph-spin"></i> Reserving Quantity...`;
    }

    try {
        const payload = {
            post_id: postId,
            organization_id: auth.ngo_id || auth.id,
            organization_name: auth.organization || auth.name,
            requested_quantity: requestedQty,
            preferred_pickup_time: pickupTime,
            message: message
        };

        const res = await authFetch(`${API_BASE}/api/redistribution/requests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        if (!res.ok) {
            // E.g. 400 "Only 15.0 kg is currently available."
            if (errAlert) {
                errAlert.textContent = data.detail || 'Failed to submit food request.';
                errAlert.classList.remove('hidden');
            }
            return;
        }

        showToast(`Request for ${requestedQty} units submitted! Held as RESERVED for ${auth.organization || 'your organization'}.`, 'success');
        closeRequestFoodModal();

        // Navigate to My Requests to view the new pending reservation
        navigateTo('ngo-requests');

    } catch (err) {
        console.error('Error submitting food request:', err);
        if (errAlert) {
            errAlert.textContent = 'Server connection error. Please try again.';
            errAlert.classList.remove('hidden');
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<i class="ph ph-check-circle"></i> Submit Request & Reserve`;
        }
    }
}

// --- 4.2B My Requests View (Private to Logged-in NGO) ---
async function loadNgoRequestsPage() {
    const auth = getAuth();
    if (!auth) return;

    const ngoId = auth.ngo_id || auth.id;
    const tbody = document.getElementById('ngo-my-requests-tbody');
    const countBadge = document.getElementById('ngo-my-requests-count');
    if (!tbody) return;

    try {
        const res = await authFetch(`${API_BASE}/api/redistribution/requests?organization_id=${ngoId}`);
        if (!res.ok) throw new Error('Failed to fetch requests');
        const data = await res.json();
        const requests = data.requests || [];

        if (countBadge) countBadge.textContent = `${requests.length} Requests`;

        if (requests.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">You have not submitted any food requests yet. Browse "Available Food" to request surplus batches.</td></tr>`;
            return;
        }

        tbody.innerHTML = requests.map(r => {
            const st = (r.status || '').toUpperCase();
            let badge = `<span class="badge badge-warning">PENDING (HELD)</span>`;
            if (st === 'ACCEPTED') badge = `<span class="badge badge-info">ACCEPTED</span>`;
            else if (st === 'SCHEDULED') badge = `<span class="badge badge-warning">SCHEDULED FOR PICKUP</span>`;
            else if (st === 'COLLECTED') badge = `<span class="badge badge-success">COLLECTED</span>`;
            else if (st === 'COMPLETED') badge = `<span class="badge badge-success">COMPLETED ✓</span>`;
            else if (st === 'REJECTED') badge = `<span class="badge badge-danger">REJECTED (RELEASED)</span>`;

            const reqDate = r.requested_at ? new Date(r.requested_at).toLocaleDateString() : 'Today';

            let coordText = `<span style="color: var(--text-muted); font-size: 0.78rem;">Awaiting supplier review</span>`;
            if (r.status === 'SCHEDULED' || r.status === 'COLLECTED' || r.status === 'COMPLETED') {
                coordText = `
                    <div style="font-size: 0.8rem;">
                        <strong><i class="ph ph-calendar"></i> ${r.pickup_date || 'Today'}</strong> at <strong>${r.pickup_time || '2:00 PM'}</strong>
                        <div style="color: var(--text-secondary); font-size: 0.75rem;">${r.pickup_location || 'Srinivas Canteen'}</div>
                    </div>
                `;
            } else if (r.status === 'ACCEPTED') {
                coordText = `<span class="badge badge-info">Pickup being scheduled by canteen</span>`;
            } else if (r.status === 'REJECTED') {
                coordText = `<span style="color: var(--danger-text); font-size: 0.78rem;">Quantity returned to availability</span>`;
            }

            return `
                <tr>
                    <td><strong>${r.food_item}</strong></td>
                    <td><strong style="color: var(--primary); font-size: 1.05rem;">${r.requested_quantity} ${r.unit}</strong></td>
                    <td>${reqDate}</td>
                    <td>${badge}</td>
                    <td style="font-size: 0.82rem; color: var(--text-secondary); max-width: 180px;">${r.message || '—'}</td>
                    <td>${coordText}</td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        console.error('Error loading my requests:', err);
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Failed to load requests from MySQL.</td></tr>`;
    }
}

// --- 4.2C Pickup Schedule View (Private to Logged-in NGO) ---
async function loadNgoSchedulePage() {
    const auth = getAuth();
    if (!auth) return;

    const ngoId = auth.ngo_id || auth.id;
    const tbody = document.getElementById('ngo-schedule-tbody');
    if (!tbody) return;

    try {
        const res = await authFetch(`${API_BASE}/api/redistribution/requests?organization_id=${ngoId}`);
        if (!res.ok) throw new Error('Failed to fetch schedule');
        const data = await res.json();
        const allRequests = data.requests || [];
        const scheduled = allRequests.filter(r => r.status === 'SCHEDULED' || r.status === 'ACCEPTED');

        if (scheduled.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No scheduled pickups currently pending for your organization.</td></tr>`;
            return;
        }

        tbody.innerHTML = scheduled.map(s => `
            <tr>
                <td><strong>${s.food_item}</strong></td>
                <td><strong>${s.requested_quantity} ${s.unit}</strong></td>
                <td><strong>${s.pickup_date || 'Today'}</strong></td>
                <td><strong style="color: var(--primary); font-size: 1rem;">${s.pickup_time || s.preferred_pickup_time || '2:00 PM'}</strong></td>
                <td style="font-size: 0.82rem; color: var(--text-secondary);">${s.pickup_location || 'Srinivas Campus Canteen Gate 2, Mangalore'}</td>
                <td>Srinivas Institute Canteen</td>
                <td><span class="badge ${s.status === 'SCHEDULED' ? 'badge-warning' : 'badge-info'}">${s.status}</span></td>
            </tr>
        `).join('');

    } catch (err) {
        console.error('Error loading schedule:', err);
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Failed to load schedule from MySQL.</td></tr>`;
    }
}

// --- 4.3 NGO Received Food History ---
async function loadNgoReceivedPage() {
    const auth = getAuth();
    if (!auth) return;
    const ngoId = auth.ngo_id || auth.id;
    const tbody = document.getElementById('ngo-received-tbody');
    if (!tbody) return;

    try {
        const res = await authFetch(`${API_BASE}/api/redistribution/requests?organization_id=${ngoId}`);
        if (!res.ok) throw new Error('Fetch failed');
        const data = await res.json();
        const allRequests = data.requests || [];

        const completed = allRequests.filter(r => r.status === 'COMPLETED' || r.status === 'COLLECTED');

        if (completed.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No completed food deliveries recorded yet. Once donations are accepted and collected, they will appear here.</td></tr>`;
            return;
        }

        tbody.innerHTML = completed.map(d => {
            const delDate = d.completed_at ? new Date(d.completed_at).toLocaleDateString() : (d.accepted_at ? new Date(d.accepted_at).toLocaleDateString() : 'Today');
            return `
                <tr>
                    <td><strong>${d.food_item}</strong></td>
                    <td><strong>${d.requested_quantity} ${d.unit}</strong></td>
                    <td>Srinivas Institute Canteen</td>
                    <td>${delDate}</td>
                    <td><span class="badge badge-success">${d.status} ✓</span></td>
                    <td>
                        <button class="btn-secondary" style="padding: 4px 8px; font-size: 0.78rem;" onclick="generateDonationCertificate(${d.id}, '${d.food_item}', ${d.requested_quantity}, '${d.unit}', 'Srinivas Institute Canteen')">
                            <i class="ph ph-certificate"></i> View Certificate
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Failed to load received food history.</td></tr>`;
    }
}

function generateDonationCertificate(id, item, qty, unit, canteen) {
    const text = `================================================
SERVIQO AI — VERIFIED FOOD RECOVERY CERTIFICATE
================================================
Certificate ID : SRV-REC-${id}-${Date.now().toString().slice(-4)}
Issued Date    : ${new Date().toLocaleDateString()}
Donating Source: ${canteen || 'Srinivas Institute Canteen / Kitchen'}
Recipient NGO  : Registered Humanitarian Partner

RECOVERY DETAILS:
Food Item      : ${item}
Net Quantity   : ${qty} ${unit}
Status         : Fully Received & Distributed
Humanitarian   : Nourished community care residents & avoided landfill waste.

Audited and relationally recorded in MySQL 8.0 database.
================================================`;

    const modalTitle = document.getElementById('view-don-title');
    const modalContent = document.getElementById('view-don-content');
    if (modalTitle) modalTitle.textContent = `Recovery Certificate — ${item}`;
    if (modalContent) modalContent.innerHTML = `<pre style="font-family: monospace; font-size: 0.8rem; background: var(--bg-body); padding: 1rem; border-radius: 4px; overflow-x: auto;">${text}</pre>`;

    const modal = document.getElementById('view-donation-modal');
    if (modal) modal.classList.add('active');
}

// --- 4.4 NGO Partner Canteens View ---
async function loadNgoCanteensPage() {
    const grid = document.getElementById('ngo-canteens-grid');
    if (!grid) return;

    try {
        const res = await fetch(`${API_BASE}/api/suppliers`);
        if (!res.ok) throw new Error('Suppliers fetch failed');
        const data = await res.json();
        const suppliers = data.suppliers || [];

        if (suppliers.length === 0) {
            grid.innerHTML = `<p class="text-muted" style="grid-column: 1 / -1; text-align: center;">No registered partner canteens found.</p>`;
            return;
        }

        grid.innerHTML = suppliers.map(sup => `
            <div class="card" style="margin: 0; padding: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem;">
                    <div>
                        <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0; color: var(--text-primary);">${sup.name}</h3>
                        <p style="font-size: 0.78rem; color: var(--text-muted); margin: 2px 0 0 0;"><i class="ph ph-storefront"></i> ${sup.category || 'Institutional Kitchen'}</p>
                    </div>
                    <span class="badge badge-success">Surplus: ${(sup.surplus_level || 'Moderate').toUpperCase()}</span>
                </div>
                <div style="background: var(--bg-body); padding: 0.75rem; border-radius: var(--radius-sm); font-size: 0.82rem; margin: 0.65rem 0;">
                    <div style="margin-bottom: 3px;"><strong>Manager:</strong> ${sup.manager || 'Rohan Sharma'}</div>
                    <div style="margin-bottom: 3px;"><strong>Direct Phone:</strong> ${sup.phone || '+91 98450 12345'}</div>
                    <div style="margin-bottom: 3px;"><strong>Surplus Categories:</strong> ${Array.isArray(sup.available_items) ? sup.available_items.join(', ') : 'Cooked Meals, Rice, Curries'}</div>
                    <div><strong>Address:</strong> ${sup.address || 'Srinivas Campus, Valachil, Mangalore'}</div>
                </div>
                <a href="tel:${sup.phone || ''}" class="btn-secondary btn-full" style="padding: 0.5rem; font-size: 0.82rem; text-decoration: none; text-align: center; display: block;">
                    <i class="ph ph-phone"></i> Contact Canteen Kitchen
                </a>
            </div>
        `).join('');

    } catch (err) {
        grid.innerHTML = `<p class="text-muted" style="grid-column: 1 / -1; text-align: center;">Failed to load canteens from MySQL.</p>`;
    }
}

// --- 4.5 NGO Recovery Audit Trail ---
async function loadNgoHistoryPage() {
    const auth = getAuth();
    if (!auth) return;
    const ngoId = auth.ngo_id || auth.id;
    const tbody = document.getElementById('ngo-history-tbody');
    if (!tbody) return;

    try {
        const res = await authFetch(`${API_BASE}/api/donations?ngo_id=${ngoId}`);
        if (!res.ok) throw new Error('Fetch failed');
        const data = await res.json();
        const donations = data.donations || [];

        if (donations.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No audit trail records found.</td></tr>`;
            return;
        }

        tbody.innerHTML = donations.map(d => {
            const st = (d.status || '').toUpperCase();
            let badgeClass = 'badge-warning';
            if (st === 'ACCEPTED' || st === 'APPROVED') badgeClass = 'badge-info';
            else if (st === 'COMPLETED' || st === 'DISTRIBUTED') badgeClass = 'badge-success';
            else if (st === 'REJECTED') badgeClass = 'badge-danger';

            const dateStr = d.created_at ? new Date(d.created_at).toLocaleString() : 'Recent';

            return `
                <tr>
                    <td style="font-size: 0.82rem; color: var(--text-secondary);">${dateStr}</td>
                    <td><strong>${d.item_name}</strong></td>
                    <td>${d.quantity} ${d.unit}</td>
                    <td>${d.supplier_name || 'Srinivas Canteen'}</td>
                    <td><span class="badge ${badgeClass}">${st}</span></td>
                    <td>
                        <button class="btn-secondary" style="padding: 3px 8px; font-size: 0.75rem;" onclick="openViewDonationModal(${d.id})">
                            <i class="ph ph-eye"></i> View Log
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Failed to load audit log.</td></tr>`;
    }
}

// --- 4.6 NGO Analytics & Relief Trends ---
async function loadNgoAnalyticsPage() {
    const auth = getAuth();
    if (!auth) return;
    const ngoId = auth.ngo_id || auth.id;

    try {
        const res = await authFetch(`${API_BASE}/api/analytics/ngo?ngo_id=${ngoId}`);
        if (!res.ok) throw new Error('NGO Analytics fetch failed');
        const data = await res.json();

        const elIntake = document.getElementById('ngo-ana-intake');
        const elRate = document.getElementById('ngo-ana-acc-rate');
        const elMeals = document.getElementById('ngo-ana-meals');
        const elCanteens = document.getElementById('ngo-ana-canteens');

        if (elIntake) elIntake.textContent = `${(data.total_intake_kg || 0).toLocaleString()} kg`;
        if (elRate) elRate.textContent = `${data.acceptance_rate_pct || 0}%`;
        if (elMeals) elMeals.textContent = (data.meals_provided || 0).toLocaleString();
        if (elCanteens) elCanteens.textContent = `${data.active_partner_canteens || 1} Canteen`;

        // Partner contributions list
        renderNgoPartnerContributions(data.donor_contributions || []);

        // Intake Chart
        initNgoRecoveryChart();

    } catch (err) {
        console.error('Error loading NGO analytics:', err);
    }
}

function renderNgoPartnerContributions(contributions) {
    const list = document.getElementById('ngo-partner-contributions-list');
    if (!list) return;

    if (contributions.length === 0) {
        list.innerHTML = `<p class="text-muted" style="font-size: 0.85rem;">No donor contributions recorded yet.</p>`;
        return;
    }

    list.innerHTML = contributions.map(c => `
        <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.84rem; font-weight: 600; margin-bottom: 4px;">
                <span>${c.canteen_name} (${c.donations_count} deliveries)</span>
                <span style="color: var(--primary);">${c.total_kg} kg (${c.percentage}%)</span>
            </div>
            <div style="height: 8px; background: var(--border-color); border-radius: 4px; overflow: hidden;">
                <div style="width: ${c.percentage}%; height: 100%; background: var(--primary);"></div>
            </div>
        </div>
    `).join('');
}

async function initNgoRecoveryChart() {
    const ctx = document.getElementById('ngoRecoveryChart');
    if (!ctx) return;

    let labels = [];
    let receivedData = [];
    let distributedData = [];

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/donation-trend?limit=7`);
        if (res.ok) {
            const data = await res.json();
            labels = data.labels || [];
            receivedData = data.received_quantity || [];
            distributedData = data.distributed_quantity || [];
        }
    } catch (e) {}

    if (labels.length === 0) {
        labels = ['Historical Data'];
        receivedData = [0];
        distributedData = [0];
    }

    if (ngoRecoveryChartInstance) {
        ngoRecoveryChartInstance.destroy();
    }

    ngoRecoveryChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Food Received (kg)',
                    data: receivedData,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.12)',
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Community Distributed (kg)',
                    data: distributedData,
                    borderColor: '#2ca85b',
                    backgroundColor: 'rgba(44, 168, 91, 0.08)',
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', font: { family: 'Inter', size: 12, weight: 600 } } }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { family: 'Inter' } } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.08)' }, ticks: { color: '#94a3b8', font: { family: 'Inter' } }, beginAtZero: true }
            }
        }
    });
}

// --- 4.7 NGO Announcements View ---
async function loadNgoAnnouncementsPage() {
    const feed = document.getElementById('ngo-announcements-feed');
    if (!feed) return;

    try {
        const res = await fetch(`${API_BASE}/api/announcements?audience=ngo`);
        if (!res.ok) throw new Error('Fetch failed');
        const data = await res.json();
        const items = data.announcements || [];

        if (items.length === 0) {
            feed.innerHTML = `
                <div style="text-align: center; padding: 2.5rem 1rem; color: var(--text-muted); background: var(--bg-card); border: 1px dashed var(--border-color); border-radius: var(--radius-sm);">
                    <i class="ph ph-megaphone-simple" style="font-size: 2rem; color: var(--text-muted); margin-bottom: 0.5rem; display: block;"></i>
                    <p style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">No Volunteer Announcements</p>
                    <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 0;">There are currently no active operational directives dispatched for food recovery volunteers.</p>
                </div>
            `;
            return;
        }

        feed.innerHTML = items.map(ann => {
            const isUrgent = (ann.priority || '').toLowerCase() === 'urgent';
            const badgeClass = isUrgent ? 'badge-danger' : ((ann.priority || '').toLowerCase() === 'high' ? 'badge-warning' : 'badge-info');
            return `
                <div style="border: 1px solid var(--border-color); padding: 1.15rem; border-radius: var(--radius-sm); background: var(--bg-card);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.4rem;">
                        <h4 style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary); margin: 0;">${ann.title}</h4>
                        <span class="badge ${badgeClass}">${ann.priority}</span>
                    </div>
                    <p style="font-size: 0.85rem; color: var(--text-secondary); margin: 0.4rem 0 0.6rem 0; line-height: 1.5;">${ann.message}</p>
                    <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); border-top: 1px solid var(--border-subtle); padding-top: 0.5rem; margin-top: 0.5rem;">
                        <span>From: <strong>${ann.sender || 'Canteen Administration'}</strong></span>
                        <span>Audience: <strong>${ann.recipient}</strong></span>
                    </div>
                </div>
            `;
        }).join('');

    } catch (err) {
        feed.innerHTML = `<p class="text-muted">Failed to load announcements.</p>`;
    }
}


// =========================================================================
// 5. GLOBAL MODALS, TOASTS & UI UTILITIES
// =========================================================================

function openViewDonationModal(donationId) {
    const donation = cachedDonations.find(d => d.id === donationId);
    if (!donation) return;

    const modalTitle = document.getElementById('view-don-title');
    const modalContent = document.getElementById('view-don-content');

    if (modalTitle) modalTitle.textContent = `Dispatch Log: ${donation.item_name}`;
    if (modalContent) {
        modalContent.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 0.65rem;">
                <div><strong>Donation Record ID:</strong> #${donation.id}</div>
                <div><strong>Food Item:</strong> ${donation.item_name}</div>
                <div><strong>Quantity:</strong> ${donation.quantity} ${donation.unit}</div>
                <div><strong>Source Canteen:</strong> ${donation.supplier_name || 'Srinivas Institute Canteen'}</div>
                <div><strong>Recipient NGO:</strong> ${donation.ngo_name || 'Relief Partner'}</div>
                <div><strong>Pickup Location:</strong> ${donation.pickup_address}</div>
                <div><strong>Pickup Deadline:</strong> ${donation.pickup_deadline || 'Within 3 hours'}</div>
                <div><strong>Current Status:</strong> <span class="badge badge-info">${(donation.status || '').toUpperCase()}</span></div>
                <div><strong>Dispatch Message:</strong> <p style="margin: 4px 0 0 0; background: var(--bg-body); padding: 0.6rem; border-radius: 4px;">${donation.message || 'Standard surplus food'}</p></div>
                <div><strong>Date Dispatched:</strong> ${donation.created_at ? new Date(donation.created_at).toLocaleString() : 'Recorded today'}</div>
            </div>
        `;
    }

    const modal = document.getElementById('view-donation-modal');
    if (modal) modal.classList.add('active');
}

function closeViewDonationModal() {
    const modal = document.getElementById('view-donation-modal');
    if (modal) modal.classList.remove('active');
}

function applyTheme(theme) {
    const html = document.documentElement;
    html.setAttribute('data-theme', theme);
    localStorage.setItem('serviqo_theme', theme);

    // Update theme icon
    const themeIcon = document.getElementById('themeIcon');
    if (themeIcon) {
        themeIcon.textContent = theme === 'light' ? '🌙' : '☀️';
    }

    // Update all theme button text labels across the app
    const themeTextSpans = document.querySelectorAll('.theme-btn-text');
    themeTextSpans.forEach(span => {
        span.textContent = theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode';
    });

    // Update charts dynamically if rendered
    const isLight = theme === 'light';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.08)';
    const tickColor = isLight ? '#475569' : '#94a3b8';

    [supplierDemandChartInstance, canteenAnalyticsDemandChartInstance, ngoRecoveryChartInstance].forEach(chart => {
        if (chart && chart.options && chart.options.scales) {
            if (chart.options.scales.x && chart.options.scales.x.ticks) {
                chart.options.scales.x.ticks.color = tickColor;
            }
            if (chart.options.scales.y) {
                if (chart.options.scales.y.ticks) chart.options.scales.y.ticks.color = tickColor;
                if (chart.options.scales.y.grid) chart.options.scales.y.grid.color = gridColor;
            }
            if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                chart.options.plugins.legend.labels.color = tickColor;
            }
            chart.update();
        }
    });
}

function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    applyTheme(newTheme);
    showToast(`Switched to ${newTheme} mode.`, 'info');
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'card';
    toast.style.padding = '0.75rem 1.15rem';
    toast.style.margin = '0';
    toast.style.display = 'flex';
    toast.style.alignItems = 'center';
    toast.style.gap = '0.5rem';
    toast.style.boxShadow = 'var(--shadow-lg)';
    toast.style.borderLeft = `4px solid ${type === 'success' ? 'var(--success)' : (type === 'danger' ? 'var(--danger)' : 'var(--info)')}`;
    toast.style.fontSize = '0.85rem';
    toast.style.fontWeight = '500';

    const icon = type === 'success' ? 'ph-check-circle' : (type === 'danger' ? 'ph-warning-octagon' : 'ph-info');
    toast.innerHTML = `<i class="ph ${icon}" style="font-size:1.2rem; color: ${type === 'success' ? 'var(--success)' : (type === 'danger' ? 'var(--danger)' : 'var(--info)')};"></i> <span>${message}</span>`;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3800);
}


// =========================================================================
// 5.1 NOTIFICATIONS SYSTEM (REDISTRIBUTION & REAL-TIME ALERTS)
// =========================================================================
let cachedNotifications = [];
let notifPollInterval = null;

function toggleNotificationsDropdown(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('notifications-dropdown-menu');
    if (!menu) return;

    // Close profile dropdown if open
    const profileMenu = document.getElementById('profile-dropdown-menu');
    if (profileMenu) profileMenu.classList.add('hidden');

    const isHidden = menu.classList.contains('hidden');
    if (isHidden) {
        menu.classList.remove('hidden');
        fetchNotifications();
    } else {
        menu.classList.add('hidden');
    }
}

async function fetchNotifications() {
    const auth = getAuth();
    if (!auth) return;

    try {
        const role = auth.role || 'canteen';
        const userId = auth.id;
        const ngoId = auth.ngo_id || (auth.role === 'ngo' ? auth.id : null);

        let url = `${API_BASE}/api/notifications?role=${encodeURIComponent(role)}`;
        if (userId) url += `&user_id=${encodeURIComponent(userId)}`;
        if (ngoId) url += `&ngo_id=${encodeURIComponent(ngoId)}`;

        const res = await authFetch(url);
        if (!res.ok) return;
        const data = await res.json();
        cachedNotifications = data.notifications || [];

        renderNotifications(cachedNotifications);
    } catch (e) {
        console.error('Error fetching notifications:', e);
    }
}

function renderNotifications(notifications) {
    const container = document.getElementById('notifications-list-container');
    const dot = document.getElementById('header-notif-dot');
    if (!container) return;

    const unreadCount = notifications.filter(n => !n.is_read).length;

    if (dot) {
        if (unreadCount > 0) {
            dot.classList.remove('hidden');
            dot.classList.add('has-count');
            dot.textContent = unreadCount > 9 ? '9+' : unreadCount;
        } else {
            dot.classList.add('hidden');
            dot.classList.remove('has-count');
            dot.textContent = '';
        }
    }

    if (notifications.length === 0) {
        container.innerHTML = `<div class="text-center text-muted" style="padding: 1.5rem 0; font-size: 0.82rem;">No notifications found</div>`;
        return;
    }

    container.innerHTML = notifications.slice(0, 15).map(n => {
        const timeAgo = n.created_at ? new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const unreadClass = n.is_read ? '' : 'unread';
        const type = (n.notification_type || '').toLowerCase();
        let icon = 'ph-bell';
        if (type.includes('surplus') || type.includes('redistribution')) icon = 'ph-hand-heart';
        else if (type.includes('request')) icon = 'ph-clipboard-text';
        else if (type.includes('accept')) icon = 'ph-check-circle';
        else if (type.includes('reject')) icon = 'ph-x-circle';
        else if (type.includes('pickup') || type.includes('schedule')) icon = 'ph-calendar-check';

        return `
            <div class="notif-item ${unreadClass}" onclick="markNotificationAsRead(${n.id})">
                <div class="notif-icon">
                    <i class="ph ${icon}"></i>
                </div>
                <div class="notif-content">
                    <div class="notif-title">${n.title}</div>
                    <div class="notif-message">${n.message}</div>
                    <div class="notif-time">${timeAgo}</div>
                </div>
            </div>
        `;
    }).join('');
}

async function markNotificationAsRead(notifId) {
    try {
        await authFetch(`${API_BASE}/api/notifications/${notifId}/read`, { method: 'PUT' });
        const item = cachedNotifications.find(n => n.id === notifId);
        if (item) item.is_read = true;
        renderNotifications(cachedNotifications);
    } catch (e) {
        console.error('Error marking notification read:', e);
    }
}

async function markAllNotificationsAsRead() {
    const auth = getAuth();
    if (!auth) return;

    try {
        const role = auth.role || 'canteen';
        const userId = auth.id;
        const ngoId = auth.ngo_id || (auth.role === 'ngo' ? auth.id : null);

        let url = `${API_BASE}/api/notifications/read-all?role=${encodeURIComponent(role)}`;
        if (userId) url += `&user_id=${encodeURIComponent(userId)}`;
        if (ngoId) url += `&ngo_id=${encodeURIComponent(ngoId)}`;

        await authFetch(url, { method: 'PUT' });
        cachedNotifications.forEach(n => n.is_read = true);
        renderNotifications(cachedNotifications);
        showToast('All notifications marked as read.', 'info');
    } catch (e) {
        console.error('Error marking all notifications read:', e);
    }
}


// =========================================================================
// 6. INITIAL APPLICATION MOUNT
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
    // Restore Saved Theme (defaults to light mode)
    const savedTheme = localStorage.getItem('serviqo_theme') || 'light';
    applyTheme(savedTheme);

    // Bind sidebar buttons
    const sidebarBtns = document.querySelectorAll('.sidebar-btn[data-target]');
    sidebarBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(btn.getAttribute('data-target'));
        });
    });

    // Mobile menu toggle
    const mobileBtn = document.getElementById('mobile-menu-btn');
    const sidebar = document.querySelector('.sidebar');
    if (mobileBtn && sidebar) {
        mobileBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // Close profile & notification dropdowns when clicking outside
    window.addEventListener('click', (e) => {
        const profileMenu = document.getElementById('profile-dropdown-menu');
        if (profileMenu && !profileMenu.classList.contains('hidden')) {
            if (!e.target.closest('#user-profile-btn') && !e.target.closest('#profile-dropdown-menu')) {
                profileMenu.classList.add('hidden');
            }
        }

        const notifMenu = document.getElementById('notifications-dropdown-menu');
        if (notifMenu && !notifMenu.classList.contains('hidden')) {
            if (!e.target.closest('#header-notif-btn') && !e.target.closest('#notifications-dropdown-menu')) {
                notifMenu.classList.add('hidden');
            }
        }
    });

    // Forms are bound via inline onsubmit handlers (handleLoginSubmit, handleRegisterSubmit)

    // Landing page interactive transitions & explore features
    const landingShell = document.getElementById('landingShell');
    const getStartedBtn = document.getElementById('getStartedBtn');
    const topLoginBtn = document.getElementById('topLoginBtn');
    const backBtn = document.getElementById('backBtn');
    const learnBtn = document.getElementById('learnBtn');
    const authEmail = document.getElementById('auth-email');

    function openLandingLogin() {
        if (landingShell) {
            landingShell.classList.add('show-login');
            setTimeout(() => {
                if (authEmail) authEmail.focus();
            }, 300);
        }
    }

    function closeLandingLogin() {
        if (landingShell) {
            landingShell.classList.remove('show-login');
        }
    }

    if (getStartedBtn) getStartedBtn.addEventListener('click', openLandingLogin);
    if (topLoginBtn) topLoginBtn.addEventListener('click', openLandingLogin);
    if (backBtn) backBtn.addEventListener('click', closeLandingLogin);

    if (learnBtn) {
        learnBtn.addEventListener('click', () => {
            const featuresEl = document.getElementById('features');
            if (featuresEl) {
                featuresEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        });
    }

    // Social login demo buttons
    const socialButtons = document.querySelectorAll('.social-btn');
    socialButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            showToast(`${btn.dataset.provider || 'Social'} login can be connected to OAuth.`, 'info');
        });
    });

    const forgotBtn = document.getElementById('forgotBtn');
    if (forgotBtn) {
        forgotBtn.addEventListener('click', () => {
            showToast('Password recovery can be connected to your authentication API.', 'info');
        });
    }

    // Role-dependent initial view & session restore
    syncUserInterface();
    const auth = getAuth();
    if (!auth) {
        navigateTo('login');
    } else if (isCanteenRole(auth.role)) {
        navigateTo('canteen-home');
        fetchNotifications();
        if (notifPollInterval) clearInterval(notifPollInterval);
        notifPollInterval = setInterval(fetchNotifications, 15000);
    } else {
        navigateTo('ngo-home');
        fetchNotifications();
        if (notifPollInterval) clearInterval(notifPollInterval);
        notifPollInterval = setInterval(fetchNotifications, 15000);
    }
});
