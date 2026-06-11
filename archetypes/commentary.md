---
title: "{{ replace (replaceRE `^[0-9]{4}-[0-9]{2}-` "" .Name) "-" " " | title }}"
date: {{ .Date }}
draft: true
tags:
  - notes
summary: "Manual PM note."
---

_Personal note. Not investment advice._

## Mistake

_What I got wrong._

## Decision

_What mattered._

## Process Change

_What changes next._
