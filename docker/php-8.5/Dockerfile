# noPanel v2 — Custom PHP 8.5 FPM image
# This file is a static default. The generated Dockerfile is at
# /etc/nopanel/generated/docker/php-8.5/Dockerfile (produced by nopanel commit).

FROM php:8.5-fpm-alpine

RUN docker-php-ext-install mysqli pdo pdo_mysql gd intl opcache bcmath zip

RUN pecl install redis && docker-php-ext-enable redis
RUN pecl install apcu && docker-php-ext-enable apcu

WORKDIR /var/www/html
