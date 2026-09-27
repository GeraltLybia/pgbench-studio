import type { components } from '@/types/api'
import { http } from './http'

export type Script = components['schemas']['ScriptOut']
export type Builtin = components['schemas']['BuiltinOut']
export type BuiltinName = Builtin['name']
export type ValidateResponse = components['schemas']['ValidateResponse']
export type ScriptDiagnostic = components['schemas']['DiagnosticOut']

export const scriptsApi = {
  list: () => http.get<Script[]>('/api/scripts'),
  create: (name: string, body: string) => http.post<Script>('/api/scripts', { name, body }),
  update: (id: number, name: string, body: string) =>
    http.put<Script>(`/api/scripts/${id}`, { name, body }),
  remove: (id: number) => http.delete<void>(`/api/scripts/${id}`),
  validate: (body: string, serverMajor: number | null, variables: string[]) =>
    http.post<ValidateResponse>('/api/scripts/validate', {
      body,
      server_major: serverMajor,
      variables,
    }),
  builtins: () => http.get<Builtin[]>('/api/builtins'),
}
