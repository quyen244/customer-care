// Builds n8n credential import JSON from env so no secret is committed; n8n encrypts it on import.
const env = process.env;
const required = (name) => {
  if (!env[name]) throw new Error(`missing env ${name}`);
  return env[name];
};

process.stdout.write(JSON.stringify([
  {
    id: 'ccWarehouseAlrt',
    name: 'Customer Care Warehouse (alerting_bot)',
    type: 'postgres',
    data: {
      host: 'postgres',
      port: 5432,
      database: 'customer_care',
      user: 'alerting_bot',
      password: required('ALERTING_DB_PASSWORD'),
      ssl: 'disable',
    },
  },
  {
    id: 'ccMailpitSmtp01',
    name: 'Mailpit SMTP (local email sink)',
    type: 'smtp',
    data: { host: 'mailpit', port: 1025, secure: false, disableStartTls: true, user: '', password: '' },
  },
]));
