# PHP 反序列化漏洞总结（CTF 向）

> 用途：PHP 反序列化题型的速查笔记。修复/加固同样参考本文（把 unserialize 的输入
> 纳入白名单、禁用危险 magic method 链、升级 Phar 使用为 `allowed_extensions` 校验）。

## 1. 基础原理

- `serialize()` / `unserialize()` 把对象与字符串互转。**unserialize 用户可控数据 = 可实例化任意类**。
- 反序列化触发 `__wakeup()` / `__destruct()`；属性访问触发 `__get()/__set()`；方法调用触发 `__call()`；
  字符串转换触发 `__toString()`——**POP 链就是把 gadget 类的 magic method 串成"调用任意函数"**。

## 2. 序列化格式速查

```
O:4:"User":2:{s:4:"name";s:5:"admin";s:3:"age";i:20;}
O:长度:"类名":属性数:{...}
b:1  i:20  d:1.5  s:5:"admin"  a:2:{...}  N; (NULL)
```

- **属性可见性影响序列化键名**：public → `name`；protected → `\0*\0name`；
  private → `\0类名\0name`。构造 payload 时用 `\0` 占位。
- CTF 常见考点：改 `O:` 后数字长度、用 `S:` 大写配合 `\xNN` 十六进制绕过
  `preg_match('/O:\d+/')` 过滤（`S:4:"\75ser"` = "User"）。

## 3. 常用魔术方法触发条件

| 方法 | 触发时机 |
|---|---|
| `__construct` | new 时（反序列化**不**触发） |
| `__wakeup` | unserialize 时 |
| `__destruct` | 对象销毁时（脚本结束/显式 unset） |
| `__toString` | 对象当字符串用（echo/拼接/函数参数） |
| `__call/__callStatic` | 调用不可访问方法 |
| `__get/__set` | 访问不可访问属性 |
| `__invoke` | 对象当函数调用 |
| `__sleep` | serialize 时 |

## 4. 经典利用套路

1. **无链可循时找 phar**：`phar://` 协议解析 metadata 会触发反序列化（PHP≤8.0 默认允许）。
   可疑函数：`file_exists / is_dir / filesize / file_get_contents` 等文件函数都走 phar 流包装。
   构造：`$phar->setMetadata($payload)` 后上传 phar 文件（改后缀图片/日志），URL 用 `phar://./x.jpg`。
2. **Session 反序列化**：`session.serialize_handler` 不一致（php 与 php_serialize）→
   构造 `|` 分隔符注入 session 内容。
3. **SoapClient SSRF**：`SoapClient->__call` 会发 HTTP 请求（需要 soap 扩展 + `__call` 触发），
   配 `User-Agent` 注入 CRLF 打内网。
4. **原生类利用**：无扩展时用 `DirectoryIterator`/`SplFileObject`（glob 枚举文件）、
   `SimpleXMLElement`（XXE）。
5. **字符逃逸**：过滤函数替换导致字符串变长/变短（str_replace 长度差）→ 用长度差把
   后续属性"挤出去"实现属性注入。核心公式：`注入字符数 = 替换膨胀数 × 重复次数`。

## 5. 绕过要点

- `__wakeup` 绕过：属性个数大于真实属性数时（CVE-2016-7124，PHP<5.6.25/<7.0.15）跳过 wakeup。
- 过滤 `unserialize`：找 phar 入口；过滤 `O:`：`S:` 十六进制、数组对象嵌套。
- 大小写/空白：`O:+4:`（+ 号）、`O:4 :`（部分版本容错）。

## 6. 防御（出题人/开发视角）

- 反序列化用户输入前用 `allowed_classes`：`unserialize($s, ["allowed_classes" => false])`。
- 不要把对象放进 session/cookie；phar 关闭：`allow_url_fopen=Off` 不影响 phar，
  需 php.ini `detect_unicode`/升级 PHP≥8.1（phar metadata 不再自动反序列化的方案仍在演进）。
- 审计入口：全局搜 `unserialize(`、`phar://`，沿 magic method 画 POP 链。
