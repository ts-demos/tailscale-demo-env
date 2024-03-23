import pulumi
import pulumi_kubernetes as k8s

PROJECT_NAME = pulumi.get_project()
STACK = pulumi.get_stack()

LABELS = {
    "environment": STACK,
    "project": PROJECT_NAME,
    "owner": "lbriggs",
    "deployed_by": "pulumi",
    "org": "lbrlabs",
}

CLUSTER = pulumi.StackReference(f"lbrlabs58/kubecon-demo-eks/{STACK}")
CLUSTER_NAME = CLUSTER.get_output("cluster_name")
KUBECONFIG = CLUSTER.get_output("kubeconfig")

provider = k8s.Provider(
    f"provider",
    kubeconfig=KUBECONFIG,
    opts=pulumi.ResourceOptions(parent=CLUSTER),
)

ns = k8s.core.v1.Namespace(
    "demo-streamer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="demo-streamer",
    ),
    opts=pulumi.ResourceOptions(provider=provider),
)

deployment = k8s.apps.v1.Deployment(
    "demo-streamer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=ns.metadata.name,
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=2,
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels=LABELS,
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels=LABELS,
            ),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="demo-streamer",
                        ports=[k8s.core.v1.ContainerPortArgs(container_port=8080)],
                        image="ghcr.io/ts-demos/demo-streamer:latest",
                    ),
                ]
            ),
        ),
    ),
    opts=pulumi.ResourceOptions(provider=provider, parent=ns),
)

svc = k8s.core.v1.Service(
    "demo-streamer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=ns.metadata.name,
    ),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="ClusterIP",
        selector=LABELS,
        ports=[k8s.core.v1.ServicePortArgs(port=8080, target_port=8080)],
    ),
    opts=pulumi.ResourceOptions(provider=provider, parent=ns),
)

ngress = k8s.networking.v1.Ingress(
    "demo-streamer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=ns.metadata.name,
    ),
    spec=k8s.networking.v1.IngressSpecArgs(
        default_backend=k8s.networking.v1.IngressBackendArgs(
            service=k8s.networking.v1.IngressServiceBackendArgs(
                name=svc.metadata.name,
                port=k8s.networking.v1.ServiceBackendPortArgs(
                    number=8080,
                ),
            )
        ),
        ingress_class_name="tailscale",
        tls=[
            k8s.networking.v1.IngressTLSArgs(
                hosts=["demo-streamer"],
            ),
        ],
    ),
    opts=pulumi.ResourceOptions(provider=provider, parent=svc),
)
