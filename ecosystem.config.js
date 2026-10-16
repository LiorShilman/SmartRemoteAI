// PM2: Smart Remote AI backend (plain HTTP on 127.0.0.1; TLS is terminated by IIS on 443).
module.exports = {
  apps: [
    {
      name: 'smartremote-server',
      script: 'backend/.venv/Scripts/python.exe',
      args: 'run.py',
      cwd: './backend',
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      watch: false,
      // Secrets (ACCESS_TOKEN) live in ../.env, never here.
      env_production: {
        // Loopback only: IIS (ARR) proxies https://<domain>/SmartRemoteAI/api/* to this port.
        BACKEND_HOST: '127.0.0.1',
        BACKEND_PORT: '41500',
        TRUST_PROXY: 'true',
      },
      error_file: './logs/err.log',
      out_file: './logs/out.log',
      log_file: './logs/combined.log',
      time: true,
      merge_logs: true,
      max_memory_restart: '500M',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
    },
  ],
};
