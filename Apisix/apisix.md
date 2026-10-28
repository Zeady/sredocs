#### apisix 3.13
- apisix deployment mode 切换
    - 文件驱动模式
        - 修改apisix configmap 配置，重启apisix 
```yaml
deployment:
  role: data_plane
  role_data_plane:
    config_provider: yaml
```
