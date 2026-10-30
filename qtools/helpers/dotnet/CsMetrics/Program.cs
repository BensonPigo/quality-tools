// 從標準輸入讀 .cs 檔案路徑（一行一個），輸出 JSON：每個函式的 file、name、start、end、complexity。
//
// 圈複雜度 = 1 + 判斷點數量，規則對齊 Go 的 gocyclo，再補上 C# 才有的語法：
//   +1：if（含 else if）、for、foreach、while、do、catch、
//       switch 中每個有列出值的 case 區段（一個區段列了幾個 case 都只算 1）、
//       switch 運算式中每個不是 _ 的分支、case 或 catch 的 when 條件、
//       &&、||、模式比對的 and、or、?:、??、??=
//   不加：else、switch 本身、default、break、continue、return
//
// 匿名函式和區域函式算進外層的函式，跟 gocyclo 一樣。
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

// 路徑和函式名稱可能有中文，輸入輸出都用不帶 BOM 的 UTF-8
Console.InputEncoding = new System.Text.UTF8Encoding(false);
Console.OutputEncoding = new System.Text.UTF8Encoding(false);

var results = new List<Dictionary<string, object>>();
string? path;
while ((path = Console.ReadLine()) != null)
{
    path = path.Trim();
    if (path.Length == 0) continue;
    var tree = CSharpSyntaxTree.ParseText(File.ReadAllText(path), path: path);
    foreach (var member in tree.GetRoot().DescendantNodes().Where(IsFunction))
    {
        var start = FirstTokenAfterAttributes(member).GetLocation().GetLineSpan().StartLinePosition.Line + 1;
        var end = member.GetLocation().GetLineSpan().EndLinePosition.Line + 1;
        results.Add(new()
        {
            ["file"] = path,
            ["name"] = NameOf(member),
            ["start"] = start,
            ["end"] = end,
            ["complexity"] = 1 + member.DescendantNodesAndTokens().Count(IsDecision),
        });
    }
}
Console.WriteLine(JsonSerializer.Serialize(results, new JsonSerializerOptions
{
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
}));

// 要量測的函式：有本體的方法、建構子、運算子、屬性存取子、用 => 寫的屬性。不含區域函式（算進外層）。
static bool IsFunction(SyntaxNode n) => n switch
{
    BaseMethodDeclarationSyntax m => m.Body != null || m.ExpressionBody != null,
    AccessorDeclarationSyntax a => a.Body != null || a.ExpressionBody != null,
    BasePropertyDeclarationSyntax p => p is PropertyDeclarationSyntax { ExpressionBody: not null }
                                       || p is IndexerDeclarationSyntax { ExpressionBody: not null },
    _ => false,
};

static bool IsDecision(SyntaxNodeOrToken x)
{
    if (x.IsToken)
    {
        return x.Kind() is SyntaxKind.AmpersandAmpersandToken or SyntaxKind.BarBarToken
            or SyntaxKind.QuestionQuestionToken or SyntaxKind.QuestionQuestionEqualsToken;
    }
    return x.AsNode() switch
    {
        IfStatementSyntax or ForStatementSyntax or CommonForEachStatementSyntax
            or WhileStatementSyntax or DoStatementSyntax or CatchClauseSyntax
            or ConditionalExpressionSyntax or WhenClauseSyntax => true,
        CatchFilterClauseSyntax => true,
        SwitchSectionSyntax s => s.Labels.Any(l => l is not DefaultSwitchLabelSyntax),
        SwitchExpressionArmSyntax arm => arm.Pattern is not DiscardPatternSyntax,
        BinaryPatternSyntax => true, // and、or
        _ => false,
    };
}

static SyntaxToken FirstTokenAfterAttributes(SyntaxNode n)
{
    var lists = n switch
    {
        MemberDeclarationSyntax m => m.AttributeLists,
        AccessorDeclarationSyntax a => a.AttributeLists,
        _ => default,
    };
    return lists.Count > 0 ? lists.Last().GetLastToken().GetNextToken() : n.GetFirstToken();
}

// 名稱格式：外層型別.函式，屬性存取子是 型別.屬性.get
static string NameOf(SyntaxNode n)
{
    var own = n switch
    {
        MethodDeclarationSyntax m => m.Identifier.Text,
        ConstructorDeclarationSyntax c => c.Identifier.Text,
        DestructorDeclarationSyntax d => "~" + d.Identifier.Text,
        OperatorDeclarationSyntax o => "operator " + o.OperatorToken.Text,
        ConversionOperatorDeclarationSyntax c => "operator " + c.Type,
        AccessorDeclarationSyntax a => PropertyName(a.Parent?.Parent) + "." + a.Keyword.Text,
        PropertyDeclarationSyntax p => p.Identifier.Text,
        IndexerDeclarationSyntax => "this[]",
        _ => "?",
    };
    var types = n.Ancestors().OfType<BaseTypeDeclarationSyntax>().Select(t => t.Identifier.Text).Reverse();
    return string.Join(".", types.Append(own));
}

static string PropertyName(SyntaxNode? n) => n switch
{
    PropertyDeclarationSyntax p => p.Identifier.Text,
    EventDeclarationSyntax e => e.Identifier.Text,
    IndexerDeclarationSyntax => "this[]",
    _ => "?",
};
