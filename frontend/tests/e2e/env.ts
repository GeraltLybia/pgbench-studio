/** Stack under test: the bootstrap admin and the test database inside the compose network. */
function required(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is not set (see tests/e2e/README in the repository README)`)
  return value
}

export const env = {
  get adminUser() {
    return process.env.E2E_ADMIN_USER ?? 'admin'
  },
  get adminPassword() {
    return required('E2E_ADMIN_PASSWORD')
  },
  dbHost: process.env.E2E_DB_HOST ?? 'pg18',
  dbPort: process.env.E2E_DB_PORT ?? '5432',
  dbName: process.env.E2E_DB_NAME ?? 'bench',
  dbUser: process.env.E2E_DB_USER ?? 'bench',
  dbPassword: process.env.E2E_DB_PASSWORD ?? 'bench',
}
