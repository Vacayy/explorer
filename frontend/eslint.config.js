import reactHooks from 'eslint-plugin-react-hooks'
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'src/api/generated/**'] },
  { linterOptions: { reportUnusedDisableDirectives: 'off' } },
  {
    files: ['**/*.{js,mjs}'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: js.configs.recommended.rules,
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser, globals: { ...globals.browser, ...globals.node } },
    plugins: { '@typescript-eslint': tseslint.plugin, 'react-hooks': reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      ...tseslint.configs.recommended.at(-1).rules,
      // TypeScript's build already checks names and unused declarations. Existing API
      // view models contain intentional any fields; runtime contracts handle the boundary.
      'react-hooks/rules-of-hooks': 'error',
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
]
