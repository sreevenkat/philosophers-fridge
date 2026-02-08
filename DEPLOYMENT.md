# Deployment Guide: Philosophers Fridge

## Quick Deploy Options

### Option 1: Railway (Recommended) ⭐

Railway offers the easiest deployment experience with automatic builds, persistent storage, and custom domains.

### Option 2: Docker on Your Server

If you have your own EC2 or VPS server, use `docker-compose up -d`.

---

## Railway Deployment

### Prerequisites
- GitHub account
- Railway account (https://railway.app)
- Resend account for email (https://resend.com)

### Step 1: Push to GitHub

```bash
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### Step 2: Create Railway Project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Authorize Railway and select your `philosophers-fridge` repository
5. Railway will auto-detect the Dockerfile and start building

### Step 3: Add Persistent Volume (Important!)

SQLite database needs persistent storage:

1. In your Railway project, click on your service
2. Go to **Settings** → **Volumes**
3. Click **"Add Volume"**
4. Mount path: `/data`
5. This persists your database across deployments

### Step 4: Configure Environment Variables

In Railway dashboard → **Variables**, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `OPENAI_API_KEY` | `sk-...` | Your OpenAI key |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Or use Anthropic |
| `PREFERRED_AI` | `openai` | or `anthropic` |
| `RESEND_API_KEY` | `re_...` | From resend.com |
| `SENDER_EMAIL` | `noreply@yourdomain.com` | Verified in Resend |
| `BASE_URL` | `https://yourapp.up.railway.app` | Your Railway URL |
| `SESSION_SECRET` | `(random string)` | Generate securely |
| `DATABASE_PATH` | `/data/food_log.db` | Uses the volume |

Generate a session secret:
```bash
openssl rand -hex 32
```

### Step 5: Add Custom Domain (Optional)

1. In Railway → **Settings** → **Domains**
2. Add your custom domain
3. Configure DNS as instructed
4. Railway provides free SSL

### Step 6: Deploy!

Railway auto-deploys on every git push. You can also:
- Click **"Deploy"** in dashboard for manual deploy
- View logs in the **"Deployments"** tab

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes* | OpenAI API key for nutrition estimation |
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key (alternative to OpenAI) |
| `PREFERRED_AI` | No | `openai` or `anthropic` (default: openai) |
| `RESEND_API_KEY` | Yes | For sending verification/invitation emails |
| `SENDER_EMAIL` | Yes | From address for emails (verify in Resend) |
| `BASE_URL` | Yes | Full URL of your app (for email links) |
| `SESSION_SECRET` | Yes | Secret key for session encryption |
| `DATABASE_PATH` | No | Path to SQLite file (default: food_log.db) |

*At least one AI API key is required

---

## First-Time Setup

1. **Register**: Go to `/register` and create your account
2. **First user is admin**: The first account automatically gets admin privileges
3. **Verify email**: Check your inbox and click the verification link
4. **Create household**: Go to home page and create your first household
5. **Invite others**: Use "Manage Households" to invite family members

---

## Troubleshooting

### Emails Not Sending
- Verify your Resend API key is correct
- Check if sender email domain is verified in Resend
- For testing, use `onboarding@resend.dev` (sends only to your email)

### Database Empty After Redeploy
- Make sure you've added a Railway volume mounted at `/data`
- Set `DATABASE_PATH=/data/food_log.db` in environment variables

### Verification Links Not Working
- Ensure `BASE_URL` matches your actual Railway URL
- Include `https://` in the URL

### Railway Build Failing
- Check build logs in Railway dashboard
- Ensure Dockerfile syntax is correct
- Verify requirements.txt is present

---

## Backup & Restore

### Backup Database
```bash
# SSH into container or use Railway CLI
cp /data/food_log.db /data/backup_$(date +%Y%m%d).db
```

### Using Railway CLI
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Connect to project
railway link

# Open shell
railway run bash
```

---

## Security Checklist

- [ ] Use a strong, unique `SESSION_SECRET`
- [ ] Verify your email domain in Resend for better deliverability
- [ ] Use HTTPS (Railway provides this automatically)
- [ ] Keep API keys secret (never commit to git)
- [ ] Regular database backups

---

## Cost Estimate (Railway)

- **Hobby Plan**: $5/month
  - 500 execution hours
  - 1GB persistent storage
  - Custom domains
  - More than enough for personal/family use

- **Free Trial**: $5 credit (no credit card required)
  - Good for testing the deployment
