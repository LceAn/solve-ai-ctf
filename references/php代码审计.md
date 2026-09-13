# PHP 代码审计速查（CTF 向）

## 1. 危险函数入口（审计起点）

| 类别 | 函数 |
|---|---|
| 命令执行 | system, exec, shell_exec, passthru, popen, proc_open, `` ` `` 反引号, pcntl_exec |
| 代码执行 | eval, assert, preg_replace(/e 修饰符, PHP<7), create_function(已弃用), call_user_func/array_map |
| 文件 | include/require(_once), file_get_contents, file_put_contents, fopen, readfile, unlink, copy, rename |
| 反序列化 | unserialize, phar:// 流 |
| 回调 | usort/uasort/preg_replace_callback + 可控回调名 |
| SSRF | curl_exec, file_get_contents(http://), fsockopen |

## 2. 弱类型比较坑

```php
"admin" == 0        → true  (PHP<8：字符串转数字)
"0e123" == "0e456"  → true  (科学计数法 md5 碰撞常见值：QNKCDZO/240610708/s878926199a)
md5($str) == md5($str2) 且 $str != $str2 → 数组绕过：a[]=1&b[]=2（md5(数组) 为 NULL 报 warning）
json {"key":true} 与 "key"=="1" 比较陷阱
is_numeric(" 123") → true（前导空格）；"123\n" 也 true
in_array("1abc", [0,1,2]) → true（松散比较）
strpos 返回 0 时用 == 判断会误判 → 必须 !== false
```

## 3. 变量覆盖

```php
extract($_GET);                    // extract 覆盖已有变量
parse_str($str);                   // 同上
$$key = $value;                    // 可变变量（foreach $_GET 常见）
import_request_variables("gpc");   // 旧版本
```
利用：题目常设 `$flag` 不可控，但 `extract($_GET)` 后 `?flag=1` 直接覆盖；或配合
`$_GET['_']` + `$$` 调用函数。

## 4. 伪协议与包含

```
php://filter/read=convert.base64-encode/resource=index.php     # 读源码
php://filter/write=convert.base64-decode/resource=shell.php    # 写（需 include 可控）
data://text/plain,<?php system('id')?>                        # 需要 allow_url_include
php://input  + POST body                                       # 同上
```
- `read=convert.iconv.utf-8.utf-7` 等编码链可绕部分过滤（iconv trap：utf-7 编码后字符集变化绕 str_replace）。

## 5. 正则与执行流

- `preg_replace("/x/e", $code, $input)`（PHP<7）：匹配替换后 eval 执行。
- `preg_match("/^flag$/", $input)` → 末尾加 `\n`（$ 匹配换行前的位置，用 `/s` 修复）。
- `pcntl_signal`/`register_shutdown_function` 可作为执行流跳板。

## 6. 常见 CTF 套路

- `if(preg_match('/flag/', $file)) die(); include($file);` → data:// 或 php://filter 读 flag.php 源码。
- `intval()` 截断：`intval("1e3")=1`、`intval("0x1a")=0`（PHP<8 不识别 hex）；`intval(" 12")=12`。
- `is_numeric` 弱类型 + switch 松散比较。
- MD5/SHA1 数组绕过、`md5("240610708")=="0e..."` 碰撞对（stronger: sha1 碰撞数组绕过）。
- `str_replace` 过滤不可重入：双写 `flaflagg` → 替换一次后还原。
- `trim`/`preg_match('/^\d+$/')` 与 `%0a` 截断。

## 7. 审计工具

```
php -l file.php                          # 语法检查
用 grep 定位入口：grep -rn "unserialize\|eval(\|assert(\|system(" --include="*.php" .
变量追踪：从 $_GET/$_POST/$_REQUEST/$_COOKIE 流向危险函数（污点分析思路）
```

## 8. PHP 7/8 差异要点

- PHP8：字符串与数字比较改语义（"admin"==0 → false）；`preg_replace /e` 移除；
  `create_function` 移除；`unserialize` 第二参数 allowed_classes 更严格默认。
- 命名参数、match 表达式、`?->` 空安全运算符（新攻击面少，防御面增加）。
