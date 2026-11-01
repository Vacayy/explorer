// Discover explicitly typed JSON calls for routes without FastAPI response models.
// Uses the TypeScript checker (including null/undefined), not textual type parsing.
import { createRequire } from 'node:module'
// The schema generator and compiler must use the same AST/type flag version.
const ts = createRequire(import.meta.resolve('typescript-json-schema'))('typescript')
import { buildGenerator } from 'typescript-json-schema'
import { resolve } from 'node:path'

export function frontendContracts(root, unmodeled) {
  const configPath = `${root}frontend/tsconfig.app.json`
  const parsed = ts.getParsedCommandLineOfConfigFile(configPath, { strictNullChecks: true }, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: diagnostic => { throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')) } })
  const program = ts.createProgram(parsed.fileNames, parsed.options)
  const checker = program.getTypeChecker()
  const printer = ts.createPrinter()
  const aliases = []
  const candidates = []
  const seen = new Set()
  const shape = path => path.replace(/\{[^}]*\}/g, '{}').replace(/\/$/, '')
  const unresolved = []

  function literal(node, depth = 0) {
    if (!node || depth > 4) return '{parameter}'
    if (ts.isStringLiteralLike(node)) return node.text
    if (ts.isTemplateExpression(node)) return node.head.text + node.templateSpans.map(span => (['query', 'qs'].includes(span.expression.getText()) && !node.head.text.endsWith('/') ? '' : literal(span.expression, depth + 1)) + span.literal.text).join('')
    if (ts.isIdentifier(node)) {
      const declaration = checker.getSymbolAtLocation(node)?.valueDeclaration
      if (declaration && ts.isVariableDeclaration(declaration) && declaration.initializer) return literal(declaration.initializer, depth + 1)
    }
    return '{parameter}'
  }
  const property = (node, name) => ts.isObjectLiteralExpression(node) ? node.properties.find(p => ts.isPropertyAssignment(p) && p.name.getText().replace(/['"]/g, '') === name)?.initializer : undefined
  function visit(node, source) {
    if (ts.isCallExpression(node)) {
      const name = node.expression.getText(source)
      let method, url, explicitType
      let discoveryAction = false
      if (['apiQuery', 'apiComputeQuery'].includes(name)) {
        method = name === 'apiQuery' ? 'get' : 'post'
        url = property(node.arguments[0], 'url')
      } else if (/^api\.(get|post|patch|put|delete)$/.test(name)) {
        method = name.split('.')[1]; url = node.arguments[0]
      } else if (name === 'getJson' || name === 'postJson') {
        method = name === 'getJson' ? 'get' : 'post'; url = node.arguments[0]
      } else if (name === 'request' && source.fileName.endsWith('/hooks/useMarketAnalysis.ts')) {
        method = node.arguments[1] && node.arguments[1].getText() !== 'undefined' ? 'post' : 'get'
        url = node.arguments[0]
      } else if (name === 'discoveryRequest') {
        method = node.arguments[1] && node.arguments[1].getText() !== 'undefined' ? 'post' : 'get'
        url = node.arguments[0]
      }
      if (ts.isPropertyAccessExpression(node.expression) && ['mutate', 'mutateAsync'].includes(node.expression.name.text)) {
        const declaration = checker.getSymbolAtLocation(node.expression.expression)?.valueDeclaration
        const hook = declaration && ts.isVariableDeclaration(declaration) ? declaration.initializer : undefined
        if (hook && ts.isCallExpression(hook) && hook.expression.getText(source) === 'useDiscoveryAction') {
          method = 'post'; url = property(node.arguments[0], 'path'); explicitType = hook.typeArguments?.[0]; discoveryAction = true
        }
      }
      if (method) for (const urlNode of url && ts.isConditionalExpression(url) ? [url.whenTrue, url.whenFalse] : [url]) {
        let path = literal(urlNode).split('?')[0].replace(/^https?:\/\/[^/]+/, '')
        if (name === 'request') path = '/api/analysis/runs' + path
        if (name === 'discoveryRequest' || discoveryAction) path = '/api/analysis/discovery' + path
        const operation = unmodeled.find(op => op.method === method && shape(op.path) === shape(path))
        if (operation) {
          let typeNode = explicitType ?? node.typeArguments?.[0]
          // Older wrappers put the response type on useQuery rather than api.get.
          if (!typeNode) {
            let parent = node.parent
            while (parent && !ts.isSourceFile(parent)) {
              if (ts.isAsExpression(parent)) { typeNode = parent.type; break }
              if (ts.isCallExpression(parent) && ['useQuery', 'useMutation'].includes(parent.expression.getText(source)) && parent.typeArguments?.length) { typeNode = parent.typeArguments[0]; break }
              if (ts.isArrowFunction(parent) || ts.isFunctionExpression(parent)) {
                const context = checker.getContextualType(parent)
                const signature = context && checker.getSignaturesOfType(context, ts.SignatureKind.Call)[0]
                const expected = signature && checker.getAwaitedType(checker.getReturnTypeOfSignature(signature))
                if (expected && !(expected.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter | ts.TypeFlags.Void))) {
                  typeNode = checker.typeToTypeNode(expected, undefined, ts.NodeBuilderFlags.UseFullyQualifiedType | ts.NodeBuilderFlags.NoTruncation)
                  // Synthesized type nodes cannot be resolved back through getTypeFromTypeNode.
                  typeNode.contractType = expected
                  break
                }
              }
              parent = parent.parent
            }
          }
          if (typeNode) {
            const type = typeNode.contractType ?? checker.getTypeFromTypeNode(typeNode)
            if (!(type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter))) {
              const rendered = checker.typeToTypeNode(type, undefined, ts.NodeBuilderFlags.UseFullyQualifiedType | ts.NodeBuilderFlags.NoTruncation)
              const typeText = printer.printNode(ts.EmitHint.Unspecified, rendered, source).replace(/import\("([^"]+)"\)/g, (_m, path) => `import(${JSON.stringify(resolve(path))})`)
              const key = `${method} ${operation.path} ${typeText}`
              if (!seen.has(key)) {
                seen.add(key)
                const symbol = `ResponseContract${aliases.length}`
                aliases.push(`export type ${symbol} = ${typeText}`)
                candidates.push({ ...operation, symbol, source: source.fileName.replace(root, '') })
              }
            }
          }
        }
      }
    }
    ts.forEachChild(node, child => visit(child, source))
  }
  for (const source of program.getSourceFiles().filter(source => source.fileName.startsWith(`${root}frontend/src/`) && !source.fileName.includes('/api/generated/'))) visit(source, source)

  // A virtual source file avoids editing source files or checking temporary aliases into git.
  const virtualPath = `${root}frontend/src/api/__response_contracts__.ts`
  const sourceText = aliases.join('\n')
  const host = ts.createCompilerHost(parsed.options)
  const getSourceFile = host.getSourceFile.bind(host)
  host.getSourceFile = (path, languageVersion, ...args) => path === virtualPath ? ts.createSourceFile(path, sourceText, languageVersion, true) : getSourceFile(path, languageVersion, ...args)
  const schemaProgram = ts.createProgram([...parsed.fileNames, virtualPath], parsed.options, host)
  const invalidLines = new Set(schemaProgram.getSemanticDiagnostics(schemaProgram.getSourceFile(virtualPath)).map(d => d.file.getLineAndCharacterOfPosition(d.start).line))
  const generator = buildGenerator(schemaProgram, { required: true, strictNullChecks: true, ignoreErrors: true, ref: true, aliasRef: true, topRef: false })
  return {
    contracts: candidates.flatMap((candidate, index) => {
      if (invalidLines.has(index)) { unresolved.push({ ...candidate, type: aliases[index], reason: 'Type is not exported or cannot be resolved' }); return [] }
      try { return [{ ...candidate, schema: generator.getSchemaForSymbol(candidate.symbol) }] }
      catch (error) { unresolved.push({ ...candidate, reason: String(error) }); return [] }
    }),
    unresolved,
  }
}
