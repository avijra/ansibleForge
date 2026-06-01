"""Tests for progressive instruction disclosure topic selection."""

from __future__ import annotations

from ansible_forge.agent.prompts.topics import (
    build_topic_expansion,
    select_topics,
)


class TestSelectTopics:
    def test_terraform_keywords_match(self):
        topics = select_topics("Deploy using terraform on AWS")
        names = [t.name for t in topics]
        assert "terraform" in names

    def test_gpu_keywords_match(self):
        topics = select_topics("Install NVIDIA GPU operator with CUDA")
        names = [t.name for t in topics]
        assert "ai_ml" in names

    def test_cicd_keywords_match(self):
        topics = select_topics("Create a GitHub Actions CI/CD pipeline")
        names = [t.name for t in topics]
        assert "cicd" in names

    def test_gitops_keywords_match(self):
        topics = select_topics("Deploy with ArgoCD and Kustomize")
        names = [t.name for t in topics]
        assert "gitops" in names

    def test_onprem_keywords_match(self):
        topics = select_topics("Configure Cisco switches and NetApp storage")
        names = [t.name for t in topics]
        assert "onprem" in names

    def test_virtualization_keywords_match(self):
        topics = select_topics("Create VMware virtual machines on vSphere")
        names = [t.name for t in topics]
        assert "virtualization" in names

    def test_no_match_returns_empty(self):
        topics = select_topics("Hello, how are you?")
        assert topics == []

    def test_max_topics_limit(self):
        topics = select_topics(
            "Deploy terraform on AWS with GPU and NVIDIA CUDA and argocd gitops",
            max_topics=2,
        )
        assert len(topics) <= 2


class TestBuildTopicExpansion:
    def test_returns_content_on_match(self):
        expansion = build_topic_expansion("Install terraform infrastructure")
        assert "Terraform" in expansion or "terraform" in expansion

    def test_returns_empty_on_no_match(self):
        expansion = build_topic_expansion("Just say hello")
        assert expansion == ""
