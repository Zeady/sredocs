#### apisix 3.13
- apisix deployment mode 切换
    - 文件驱动模式
        - 修改apisix configmap 配置，重启apisix 
        - 修改apisix-ingress-controller configmap ，重启ingress-controller
```yaml
# apisix configmap
deployment:
  role: data_plane
  role_data_plane:
    config_provider: yaml
# apisix-ingress-controller configmap
ingress-controller:
  enabled: true
  config:
    provider:
      type: apisix-standalone
```
  - api模式切换
    - 修改并重启组件
```yaml
# apisix configmap
deployment:
  role: traditional
  role_traditional:
    config_provider: yaml
# apisix-ingress-controller configmap
ingress-controller:
  enabled: true
  config:
    provider:
      type: apisix-standalone
```

---
- apisix manager 负责把 Kubernetes 资源转换成网关配置，adc-server 负责把配置同步到 APISIX。真正转发业务请求的是 APISIX Gateway 
- 两种模式开启后，ui端口无法访问，UI默认都是读取etcd数据
---
