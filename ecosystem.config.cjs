module.exports = {
  apps: [
    {
      name: 'blox-gui',
      script: 'python',
      args: '-m streamlit run streamlit_app.py --server.port 3000 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false',
      cwd: '/home/user/webapp',
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      env: { PYTHONUNBUFFERED: '1' }
    },
    {
      name: 'blox-watcher',
      script: 'python',
      args: '-m blox_trade_finder.watcher --config config/watcher.json',
      cwd: '/home/user/webapp',
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      env: { PYTHONUNBUFFERED: '1' }
    }
  ]
}
