# Deployment Guide: Philosophers Fridge on EC2 with Docker

## Prerequisites
- EC2 server with Docker and Docker Compose installed
- Tailscale (if accessing via Tailscale network)
- Resend account for sending emails (https://resend.com)
- Domain name (optional, but recommended for HTTPS and email deliverability)

---

## Step 1: Set Up Resend for Email

### 1.1 Create Resend Account

1. Go to [Resend](https://resend.com) and create an account
2. Navigate to **API Keys** and create a new API key
3. Copy the API key (starts with `re_`)

### 1.2 Configure Sender Email

**For Testing:**
- Use `onboarding@resend.dev` as the sender
- Note: This only works when sending to your own email address

**For Production:**
1. Go to **Domains** in Resend
2. Add your domain (e.g., `yourdomain.com`)
3. Add the DNS records Resend provides
4. Once verified, use `noreply@yourdomain.com` as sender

---

## Step 2: Deploy on EC2

### 2.1 Clone the Repository

```bash
# SSH into your EC2 server
ssh your-ec2-server

# Clone the repo
git clone https://github.com/your-username/philosophers-fridge.git
cd philosophers-fridge
```

### 2.2 Create Environment File

```bash
# Copy the production template
cp .env.production .env

# Edit with your values
nano .env
```

Fill in your `.env` file:

```env
# Resend API Key (from Step 1)
RESEND_API_KEY=re_your_resend_api_key

# Sender email - verified in Resend
SENDER_EMAIL=noreply@yourdomain.com

# AI API Key (at least one required for nutrition estimation)
OPENAI_API_KEY=sk-your-openai-key
# OR
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key

# Which AI to use
PREFERRED_AI=openai

# Generate a random secret
SESSION_SECRET=your-random-secret-here

# Your access URL (used in email links)
BASE_URL=http://your-ec2-tailscale-name:8080
```

Generate a secure session secret:
```bash
openssl rand -hex 32
```

### 2.3 Create Docker Network

```bash
docker network create web
```

### 2.4 Build and Run

```bash
# Build and start the container
docker compose up -d --build

# Check logs
docker compose logs -f
```

---

## Step 3: Access the Application

### Via Tailscale
If your EC2 is on your Tailscale network:
```
http://your-ec2-tailscale-name:8080
```

### Via Domain (with Traefik/Nginx)
If you have a reverse proxy, configure it to proxy to port 8080.

---

## Step 4: User Registration & Login

### How It Works

1. **First User is Admin**: The first person to register becomes an admin
2. **Email Verification Required**: Users must verify their email before logging in
3. **Password Requirements**: Minimum 8 characters

### User Flow

1. User goes to `/register`
2. Fills in name, email, password
3. Receives verification email
4. Clicks verification link
5. Email is verified, user is logged in
6. Can now access the application

---

## Step 5: Inviting Users to Households

### As an Admin

1. Log in to your account
2. Go to **Manage Households**
3. Click **Invite Member**
4. Enter the invitee's email address
5. An invitation email is sent automatically

### Invitation Flow

1. Invitee receives email with invitation link
2. If new user: redirected to register with invite code
3. If existing user: redirected to login
4. After registration/login, they're automatically added to the household

---

## Step 6: Make a User Admin (Optional)

If you need to make an additional user an admin:

```bash
# Enter the container
docker compose exec philosophers-fridge bash

# Use SQLite to update
sqlite3 food_log.db
```

```sql
-- Find your user
SELECT id, name, email, role FROM users;

-- Make them admin
UPDATE users SET role = 'admin' WHERE email = 'user@example.com';

-- Verify
SELECT * FROM users WHERE role = 'admin';
```

---

## Common Commands

```bash
# Start the app
docker compose up -d

# Stop the app
docker compose down

# View logs
docker compose logs -f

# Rebuild after code changes
docker compose up -d --build

# Access container shell
docker compose exec philosophers-fridge bash

# Backup database
docker compose exec philosophers-fridge cat /app/food_log.db > backup.db
```

---

## Troubleshooting

### Emails Not Sending

1. Check Resend API key is correct
2. Verify sender domain in Resend dashboard
3. Check container logs for errors: `docker compose logs -f`

### Verification Links Not Working

- Ensure `BASE_URL` in `.env` matches your actual access URL
- Include the port if applicable (e.g., `:8080`)

### Database Not Persisting

- Ensure the `./food_log.db` volume mount exists
- Check file permissions

### Can't Connect to App

- Verify the container is running: `docker compose ps`
- Check if port 8080 is open in EC2 security group (or use Tailscale)

---

## Security Notes

1. **Session Secret**: Always use a unique, randomly generated secret
2. **HTTPS**: For production, set up a reverse proxy with SSL
3. **Email Verification**: Users must verify their email before logging in
4. **Password Hashing**: Passwords are hashed using bcrypt

---

## Production Recommendations

1. **Use HTTPS**: Set up a reverse proxy (Traefik, Nginx, Caddy) with Let's Encrypt SSL
2. **Verify Domain in Resend**: Better email deliverability than using `onboarding@resend.dev`
3. **Backup Database**: Schedule regular backups of `food_log.db`
4. **Consider PostgreSQL**: For heavy usage, migrate from SQLite to PostgreSQL
5. **Monitor Logs**: Set up log monitoring for error detection
