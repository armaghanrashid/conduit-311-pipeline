resource "aws_ecr_repository" "conduit" {
  name                 = var.name_prefix
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "conduit" {
  repository = aws_ecr_repository.conduit.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the ten most recent images"

        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
