// 從標準輸入讀 .js/.ts 檔案路徑（一行一個），輸出 JSON：每個函式的 file、name、start、end、complexity。
//
// 用法：node complexity.cjs <typescript 套件的目錄>
// 用 TypeScript 的解析器，所以 JavaScript、TypeScript、JSX、TSX 都能讀。由 lang_js.py 呼叫。
//
// 圈複雜度 = 1 + 判斷點數量，規則對齊 Go 的 gocyclo：
//   +1：if（含 else if）、for、for...in、for...of、while、do...while、catch、
//       switch 中每組 case（連在一起、中間沒有程式的 case 算同一組，等同 Go 一個 case 列多個值）、
//       ?:、&&、||、??、&&=、||=、??=
//   不加：else、switch 本身、default、?.（選擇性串連）、參數預設值
//
// 要量測的函式：最外層的函式宣告、class 的方法和建構子、getter/setter，以及指定給變數、
// 物件屬性或 class 欄位的箭頭函式和函式運算式。函式裡面的函式（例如 callback）算進外層，跟 gocyclo 一樣。
"use strict";
const fs = require("fs");
const path = require("path");
const ts = require(process.argv[2]);

const KINDS = { ".ts": ts.ScriptKind.TS, ".mts": ts.ScriptKind.TS, ".cts": ts.ScriptKind.TS, ".tsx": ts.ScriptKind.TSX, ".jsx": ts.ScriptKind.JSX };
const LOGICAL = new Set([
  ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken,
  ts.SyntaxKind.AmpersandAmpersandEqualsToken, ts.SyntaxKind.BarBarEqualsToken, ts.SyntaxKind.QuestionQuestionEqualsToken,
]);

const results = [];
for (const file of fs.readFileSync(0, "utf8").split(/\r?\n/).filter(Boolean)) {
  const kind = KINDS[path.extname(file)] ?? ts.ScriptKind.JS;
  const sf = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, kind);
  const line = (pos) => sf.getLineAndCharacterOfPosition(pos).line + 1;

  const visit = (node, className) => {
    if (isFunction(node) && node.body) {
      const start = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      results.push({
        file,
        name: nameOf(node, className),
        start: start.line + 1,
        // 從 0 起算的欄位。lang_js.py 用它排除 `const f = () => {...}` 這種宣告敘述：
        // 宣告在載入時就會執行，不能算成函式有被測試
        startColumn: start.character,
        end: line(node.end),
        complexity: 1 + countDecisions(node.body),
      });
      return; // 裡面的函式算進這個函式
    }
    if (ts.isClassLike(node)) {
      className = node.name ? node.name.text : className;
    }
    ts.forEachChild(node, (child) => visit(child, className));
  };
  visit(sf, undefined);
}
process.stdout.write(JSON.stringify(results));

function isFunction(n) {
  return ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n) || ts.isConstructorDeclaration(n)
    || ts.isGetAccessorDeclaration(n) || ts.isSetAccessorDeclaration(n)
    || ts.isArrowFunction(n) || ts.isFunctionExpression(n);
}

function countDecisions(root) {
  let n = 0;
  const walk = (node) => {
    switch (node.kind) {
      case ts.SyntaxKind.IfStatement:
      case ts.SyntaxKind.ForStatement:
      case ts.SyntaxKind.ForInStatement:
      case ts.SyntaxKind.ForOfStatement:
      case ts.SyntaxKind.WhileStatement:
      case ts.SyntaxKind.DoStatement:
      case ts.SyntaxKind.CatchClause:
      case ts.SyntaxKind.ConditionalExpression:
        n++;
        break;
      case ts.SyntaxKind.CaseClause:
        if (node.statements.length > 0) n++; // 空的 case 和下一個 case 算同一組
        break;
      case ts.SyntaxKind.BinaryExpression:
        if (LOGICAL.has(node.operatorToken.kind)) n++;
        break;
    }
    ts.forEachChild(node, walk);
  };
  walk(root);
  return n;
}

// 名稱格式：Class.method；箭頭函式和函式運算式用它被指定的名稱
function nameOf(node, className) {
  const prefix = className ? className + "." : "";
  if (ts.isConstructorDeclaration(node)) return prefix + "constructor";
  if (ts.isGetAccessorDeclaration(node)) return prefix + "get " + propName(node.name);
  if (ts.isSetAccessorDeclaration(node)) return prefix + "set " + propName(node.name);
  if (ts.isMethodDeclaration(node)) return prefix + propName(node.name);
  if (ts.isFunctionDeclaration(node)) return node.name ? node.name.text : "(default)";
  if (ts.isFunctionExpression(node) && node.name) return node.name.text;
  const p = node.parent;
  if (ts.isVariableDeclaration(p) || ts.isPropertyAssignment(p)) return propName(p.name);
  if (ts.isPropertyDeclaration(p)) return prefix + propName(p.name);
  if (ts.isExportAssignment(p)) return "(default)";
  return "(anonymous)";
}

function propName(name) {
  return ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isPrivateIdentifier(name) ? name.text : name.getText();
}
