## Mysql 

---

#### MySQL 与 Linux 资源管理：内存、CPU、磁盘 I/O，以及如何判断实例的真实容量
-  Linux 上的 MySQL 8.0.30+/8.4 为背景。云数据库可能需要通过平台监控查看对应指标

- Mysql 内存分配
```text
MySQL 内存
├── 全局结构
│   ├── InnoDB Buffer Pool
│   ├── 日志缓冲区
│   ├── 数据字典与表缓存
│   └── Performance Schema
│
├── 连接和线程
│   ├── 线程栈
│   └── 网络及会话缓冲区
│
└── SQL 执行期间的分配
    ├── 排序
    ├── JOIN
    ├── 临时表
    └── 其他执行结构
```


