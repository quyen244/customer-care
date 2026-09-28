// Creates the n8n instance owner once the REST API is live (healthz turns OK before routes are mounted).
const base = 'http://localhost:5678';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  for (let attempt = 1; attempt <= 90; attempt++) {
    try {
      const settings = await (await fetch(`${base}/rest/settings`)).json();
      if (settings.data && settings.data.userManagement.showSetupOnFirstLoad === false) {
        console.log('n8n owner already set up');
        return;
      }
      const res = await fetch(`${base}/rest/owner/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: process.env.N8N_OWNER_EMAIL,
          firstName: 'Customer Care',
          lastName: 'Admin',
          password: process.env.N8N_OWNER_PASSWORD,
        }),
      });
      if (res.ok) {
        console.log(`n8n owner ${process.env.N8N_OWNER_EMAIL} created`);
        return;
      }
      console.log(`owner setup not ready yet (HTTP ${res.status}), retrying`);
    } catch {
      // server not accepting connections yet
    }
    await sleep(2000);
  }
  console.error('giving up on n8n owner setup');
})();
