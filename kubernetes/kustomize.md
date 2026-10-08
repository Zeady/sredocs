#### kustomize 


- patches写法:

  | 对比 | 第一项 | 第二项 |
  |---|---|---|
  | 补丁类型 | Strategic Merge，策略合并补丁 | JSON Patch |
  | 写法 | 描述需要修改的 YAML 结构 | 指定 `op`、`path`、`value` |
  | 容器定位 | 按容器名 `account-grpc` | 按数组下标 `0` |
  | 修改内容 | 容器镜像 | 某个环境变量的值 |
  | 顺序影响 | 容器顺序变化不影响匹配 | 容器或环境变量顺序变化可能改错字段 |

    - 例如 ：
```yaml
namespace: test

resources:
  - ../../base/deployment.yaml
  - ../../base/service.yaml

images:
  - name: harbor.test.net/api
    newTag: '5de4a1d1269'


patches:
  - target:
      group: apps
      version: v1
      kind: Deployment
      name: grpc
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: grpc
      spec:
        template:
          spec:
            containers:
              - name: grpc
                image: harbor.test.net/api:test-001
  - patch: |
      - op: replace
        path: /spec/template/spec/containers/0/env/5/value
        value: test


    target:
      kind: Deployment
      name: grpc
```