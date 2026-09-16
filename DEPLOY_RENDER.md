# Deploy LaunchSafe Live on Render

## 1. Put this project in GitHub
Create a new GitHub repository and upload the contents of this folder (not the ZIP itself).

## 2. Create the Render service
In Render, choose **New → Web Service**, connect the GitHub repository, and use:

- Runtime: Python
- Build Command: `python -m compileall .`
- Start Command: `python server.py --port $PORT`
- Health Check Path: `/health`

The included `render.yaml` can also be used with Render's Blueprint flow.

## 3. After deployment
Render supplies `RENDER_EXTERNAL_URL`. LaunchSafe uses that automatically, so generated QR codes point to the public HTTPS URL.

Open:

- Instructor: `https://YOUR-APP.onrender.com/host`
- Projector: `https://YOUR-APP.onrender.com/screen`
- Student join: `https://YOUR-APP.onrender.com/join`
- Health: `https://YOUR-APP.onrender.com/health`

When `/host` opens, the application stores the secret from the URL fragment in the browser. Keep the instructor URL private.

## Important temporary-hosting note
The app uses a local SQLite database. On a typical temporary Render deployment without a persistent disk, the game state can be lost if the service is restarted/redeployed. For a single classroom session this is usually fine. Do not treat this deployment as permanent production hosting.
